// Dumps one JSON file per event with detector hits and reconstructed objects in
// global CMS coordinates (metres), for overlay on a 3D detector model.
#include <cmath>
#include <fstream>
#include <iomanip>
#include <sstream>
#include <string>
#include <vector>
#include <algorithm>

#include "FWCore/Framework/interface/one/EDAnalyzer.h"
#include "FWCore/Framework/interface/Event.h"
#include "FWCore/Framework/interface/EventSetup.h"
#include "FWCore/Framework/interface/MakerMacros.h"
#include "FWCore/ParameterSet/interface/ParameterSet.h"
#include "FWCore/Common/interface/TriggerNames.h"
#include "DataFormats/Common/interface/TriggerResults.h"
#include "DataFormats/Common/interface/DetSetVectorNew.h"
#include "DataFormats/TrackReco/interface/Track.h"
#include "DataFormats/VertexReco/interface/Vertex.h"
#include "DataFormats/MuonReco/interface/Muon.h"
#include "DataFormats/MuonReco/interface/MuonFwd.h"
#include "DataFormats/MuonDetId/interface/MuonSubdetId.h"
#include "DataFormats/EgammaCandidates/interface/GsfElectron.h"
#include "DataFormats/EgammaCandidates/interface/Photon.h"
#include "DataFormats/EgammaCandidates/interface/PhotonFwd.h"
#include "DataFormats/JetReco/interface/PFJet.h"
#include "DataFormats/METReco/interface/PFMET.h"
#include "DataFormats/METReco/interface/PFMETCollection.h"
#include "DataFormats/HepMCCandidate/interface/GenParticle.h"
#include "DataFormats/EcalRecHit/interface/EcalRecHitCollections.h"
#include "DataFormats/HcalRecHit/interface/HcalRecHitCollections.h"
#include "DataFormats/SiPixelCluster/interface/SiPixelCluster.h"
#include "DataFormats/SiStripCluster/interface/SiStripCluster.h"
#include "DataFormats/DTRecHit/interface/DTRecSegment4DCollection.h"
#include "DataFormats/CSCRecHit/interface/CSCSegmentCollection.h"
#include "DataFormats/RPCRecHit/interface/RPCRecHitCollection.h"
#include "DataFormats/GEMRecHit/interface/GEMRecHitCollection.h"
#include "Geometry/TrackerGeometryBuilder/interface/TrackerGeometry.h"
#include "Geometry/CommonTopologies/interface/PixelTopology.h"
#include "Geometry/CommonTopologies/interface/StripTopology.h"
#include "Geometry/CommonDetUnit/interface/GlobalTrackingGeometry.h"
#include "Geometry/CaloGeometry/interface/CaloGeometry.h"
#include "Geometry/CaloGeometry/interface/CaloCellGeometry.h"
#include "Geometry/Records/interface/TrackerDigiGeometryRecord.h"
#include "Geometry/Records/interface/GlobalTrackingGeometryRecord.h"
#include "Geometry/Records/interface/CaloGeometryRecord.h"

namespace {
  // CMSSW lengths are in cm; the JSON is in metres, 0.1 mm precision.
  struct J {
    std::ostringstream s;
    J() { s << std::fixed; }
    void m(double cm) { s << std::setprecision(4) << cm / 100.; }
    void v(double x) { s << std::setprecision(3) << x; }
    void pt3(const GlobalPoint& p) { s << '['; m(p.x()); s << ','; m(p.y()); s << ','; m(p.z()); s << ']'; }
    template <class P>
    void xyz(const P& p) { s << '['; m(p.x()); s << ','; m(p.y()); s << ','; m(p.z()); s << ']'; }
  };
  const double kB = 3.8;  // T, uniform field inside the solenoid

  // Helix through the reference point in the uniform solenoid field; a is the transverse turning angle.
  GlobalPoint helixAt(const reco::Track& t, double a) {
    const double R = t.pt() / (0.299792458 * kB) * 100.;  // cm
    const double q = t.charge(), phi0 = t.phi();
    const double cx = t.vx() + R * q * std::sin(phi0), cy = t.vy() - R * q * std::cos(phi0);
    const double ph = phi0 - q * a;
    return GlobalPoint(cx - R * q * std::sin(ph), cy + R * q * std::cos(ph), t.vz() + a * R * t.pz() / t.pt());
  }
  // turning angle at the outermost hit
  double amaxOuter(const reco::Track& t) {
    if (!t.extra().isAvailable()) return 0;
    const double R = t.pt() / (0.299792458 * kB) * 100.;
    const auto& o = t.outerPosition();
    const double d = std::hypot(o.x() - t.vx(), o.y() - t.vy());
    double amax = 2 * std::asin(std::min(1.0, d / (2 * R)));
    if (std::abs(o.z() - t.vz()) > 1e-3 && std::abs(t.pz()) > 1e-6) {  // longitudinal length is exact for loopers too
      const double az = (o.z() - t.vz()) / (R * t.pz() / t.pt());
      if (az > 0 && (d / (2 * R) >= 0.999 || std::abs(az - amax) < 0.5)) amax = az;
    }
    return amax;
  }
  // turning angle where the helix leaves the cylinder r < rmax, |z| < zmax (cm)
  double amaxCylinder(const reco::Track& t, double rmax, double zmax) {
    double a = 0;
    for (; a < M_PI; a += 0.002) {
      const auto p = helixAt(t, a);
      if (p.perp() > rmax || std::abs(p.z()) > zmax) break;
    }
    return a;
  }
  std::vector<GlobalPoint> helix(const reco::Track& t, double amax, int n) {
    std::vector<GlobalPoint> v;
    for (int i = 0; i <= n; ++i) v.push_back(helixAt(t, amax * i / n));
    return v;
  }
  void points(J& j, const std::vector<GlobalPoint>& v) {
    j.s << '[';
    for (size_t i = 0; i < v.size(); ++i) { if (i) j.s << ','; j.pt3(v[i]); }
    j.s << ']';
  }
}  // namespace

class RawVizDumper : public edm::one::EDAnalyzer<> {
public:
  explicit RawVizDumper(const edm::ParameterSet& c)
      : outDir_(c.getParameter<std::string>("outDir")),
        ecalMin_(c.getParameter<double>("ecalMin")),
        hcalMin_(c.getParameter<double>("hcalMin")),
        hfMin_(c.getParameter<double>("hfMin")),
        trkPtMin_(c.getParameter<double>("trackPtMin")),
        trigT_(consumes(edm::InputTag("TriggerResults", "", "HLT"))),
        trkT_(consumes(edm::InputTag("generalTracks"))),
        vtxT_(consumes(edm::InputTag("offlinePrimaryVertices"))),
        muT_(consumes(edm::InputTag("muons"))),
        eleT_(consumes(edm::InputTag("gedGsfElectrons"))),
        phoT_(consumes(edm::InputTag("gedPhotons"))),
        jetT_(consumes(edm::InputTag("ak4PFJetsCHS"))),
        metT_(consumes(edm::InputTag("pfMet"))),
        ebT_(consumes(edm::InputTag("ecalRecHit", "EcalRecHitsEB"))),
        eeT_(consumes(edm::InputTag("ecalRecHit", "EcalRecHitsEE"))),
        hbheT_(consumes(edm::InputTag("hbhereco"))),
        hfT_(consumes(edm::InputTag("hfreco"))),
        hoT_(consumes(edm::InputTag("horeco"))),
        pixT_(consumes(edm::InputTag("siPixelClusters"))),
        strT_(consumes(edm::InputTag("siStripClusters"))),
        dtT_(consumes(edm::InputTag("dt4DSegments"))),
        cscT_(consumes(edm::InputTag("cscSegments"))),
        rpcT_(consumes(edm::InputTag("rpcRecHits"))),
        gemT_(consumes(edm::InputTag("gemRecHits"))),
        genT_(consumes(edm::InputTag("genParticles"))),
        tkGeoT_(esConsumes()),
        glGeoT_(esConsumes()),
        caloGeoT_(esConsumes()) {}

  void analyze(const edm::Event& e, const edm::EventSetup& es) override {
    const auto& tkGeo = es.getData(tkGeoT_);
    const auto& glGeo = es.getData(glGeoT_);
    const auto& caloGeo = es.getData(caloGeoT_);
    J j;
    j.s << "{\"run\":" << e.id().run() << ",\"lumi\":" << e.luminosityBlock() << ",\"event\":" << e.id().event();

    if (auto h = e.getHandle(trigT_); h.isValid()) {
      const auto& names = e.triggerNames(*h);
      j.s << ",\"hlt\":[";
      bool first = true;
      for (unsigned i = 0; i < h->size(); ++i) {
        const auto& n = names.triggerName(i);
        if (!h->accept(i) || n.rfind("HLT_", 0) != 0) continue;
        j.s << (first ? "" : ",") << '"' << n << '"';
        first = false;
      }
      j.s << ']';
    }

    // primary vertices
    j.s << ",\"vertices\":[";
    if (auto h = e.getHandle(vtxT_); h.isValid()) {
      bool first = true;
      for (const auto& v : *h) {
        if (v.isFake()) continue;
        j.s << (first ? "" : ",") << "{\"p\":";
        j.xyz(v.position());
        j.s << ",\"n\":" << v.tracksSize() << '}';
        first = false;
      }
    }
    j.s << ']';

    // tracks as helices
    j.s << ",\"tracks\":[";
    if (auto h = e.getHandle(trkT_); h.isValid()) {
      bool first = true;
      for (const auto& t : *h) {
        if (t.pt() < trkPtMin_ || !t.quality(reco::TrackBase::highPurity)) continue;
        j.s << (first ? "" : ",") << "{\"pt\":";
        j.v(t.pt());
        j.s << ",\"eta\":"; j.v(t.eta());
        j.s << ",\"phi\":"; j.v(t.phi());
        j.s << ",\"q\":" << t.charge() << ",\"nh\":" << t.numberOfValidHits() << ",\"pts\":";
        points(j, helix(t, amaxOuter(t), 28));
        j.s << '}';
        first = false;
      }
    }
    j.s << ']';

    // muons: inner-track helix out to the coil, then the track extrapolated into every chamber it crosses
    // (DT hits measure one coordinate only, so they are not used as path points)
    j.s << ",\"muons\":[";
    if (auto h = e.getHandle(muT_); h.isValid()) {
      bool first = true;
      for (const auto& mu : *h) {
        if (mu.pt() < 3 || !(mu.isGlobalMuon() || (mu.isTrackerMuon() && mu.numberOfMatchedStations() >= 2))) continue;
        j.s << (first ? "" : ",") << "{\"pt\":"; j.v(mu.pt());
        j.s << ",\"eta\":"; j.v(mu.eta());
        j.s << ",\"phi\":"; j.v(mu.phi());
        j.s << ",\"q\":" << mu.charge() << ",\"global\":" << (mu.isGlobalMuon() ? 1 : 0) << ",\"stations\":" << mu.numberOfMatchedStations() << ",\"pts\":";
        first = false;
        std::vector<GlobalPoint> pts;
        if (mu.innerTrack().isNonnull())
          pts = helix(*mu.innerTrack(), amaxCylinder(*mu.innerTrack(), 295., 600.), 48);
        else
          pts.emplace_back(mu.vx(), mu.vy(), mu.vz());
        std::vector<GlobalPoint> out;
        auto det = [&](DetId id) -> const GeomDet* { try { return glGeo.idToDet(id); } catch (...) { return nullptr; } };
        for (const auto& ch : mu.matches())
          if (const GeomDet* d = det(ch.id)) out.push_back(d->surface().toGlobal(LocalPoint(ch.x, ch.y, 0)));
        if (mu.isGlobalMuon() && mu.globalTrack()->extra().isAvailable()) {
          const auto& gt = *mu.globalTrack();
          for (auto it = gt.recHitsBegin(); it != gt.recHitsEnd(); ++it) {
            const TrackingRecHit* hit = *it;
            if (!hit->isValid() || hit->geographicalId().det() != DetId::Muon) continue;
            const int sub = hit->geographicalId().subdetId();
            if (sub != MuonSubdetId::CSC && sub != MuonSubdetId::GEM) continue;
            if (const GeomDet* d = det(hit->geographicalId())) out.push_back(d->surface().toGlobal(hit->localPosition()));
          }
          const auto& op = gt.outerPosition();
          out.emplace_back(op.x(), op.y(), op.z());
        }
        const GlobalPoint o(mu.vx(), mu.vy(), mu.vz());
        const double r0 = (pts.back() - o).mag();
        std::sort(out.begin(), out.end(), [&](const GlobalPoint& a, const GlobalPoint& b) { return (a - o).mag2() < (b - o).mag2(); });
        for (const auto& p : out)
          if ((p - o).mag() > r0 + 5.) pts.push_back(p);
        points(j, pts);
        j.s << '}';
      }
    }
    j.s << ']';

    auto cands = [&](const char* key, const auto& h, double ptMin) {
      j.s << ",\"" << key << "\":[";
      bool first = true;
      if (h.isValid())
        for (const auto& c : *h) {
          if (c.pt() < ptMin) continue;
          j.s << (first ? "" : ",") << "{\"pt\":"; j.v(c.pt());
          j.s << ",\"eta\":"; j.v(c.eta());
          j.s << ",\"phi\":"; j.v(c.phi());
          j.s << ",\"e\":"; j.v(c.energy());
          j.s << ",\"q\":" << c.charge() << '}';
          first = false;
        }
      j.s << ']';
    };
    cands("electrons", e.getHandle(eleT_), 10);
    cands("photons", e.getHandle(phoT_), 15);
    cands("jets", e.getHandle(jetT_), 30);
    if (auto h = e.getHandle(metT_); h.isValid() && !h->empty()) {
      j.s << ",\"met\":{\"pt\":"; j.v(h->front().pt());
      j.s << ",\"phi\":"; j.v(h->front().phi());
      j.s << '}';
    }

    // generator truth, simulation only: the hard-process particles after the incoming partons
    if (auto h = e.getHandle(genT_); h.isValid()) {
      j.s << ",\"gen\":[";
      bool first = true;
      for (const auto& p : *h) {
        if (!p.isHardProcess() || p.status() == 21) continue;
        j.s << (first ? "" : ",") << "{\"id\":" << p.pdgId() << ",\"st\":" << p.status() << ",\"pt\":"; j.v(p.pt());
        j.s << ",\"eta\":"; j.v(p.pt() > 1e-3 ? p.eta() : 0.);
        j.s << ",\"phi\":"; j.v(p.phi());
        j.s << ",\"m\":"; j.v(p.mass());
        j.s << ",\"mo\":" << (p.numberOfMothers() ? p.mother(0)->pdgId() : 0) << '}';
        first = false;
      }
      j.s << ']';
    }

    // calorimeter rechits: [x,y,z, E, eta, phi] at the cell centre
    auto calo = [&](const char* key, const auto& h, double emin) {
      j.s << ",\"" << key << "\":[";
      bool first = true;
      if (h.isValid())
        for (const auto& r : *h) {
          if (r.energy() < emin) continue;
          auto cell = caloGeo.getGeometry(r.detid());
          if (!cell) continue;
          const GlobalPoint& p = cell->getPosition();
          j.s << (first ? "[" : ",[");
          j.m(p.x()); j.s << ','; j.m(p.y()); j.s << ','; j.m(p.z()); j.s << ',';
          j.v(r.energy()); j.s << ','; j.v(p.eta()); j.s << ','; j.v(p.phi()); j.s << ']';
          first = false;
        }
      j.s << ']';
    };
    calo("eb", e.getHandle(ebT_), ecalMin_);
    calo("ee", e.getHandle(eeT_), ecalMin_);
    calo("hbhe", e.getHandle(hbheT_), hcalMin_);
    calo("hf", e.getHandle(hfT_), hfMin_);
    calo("ho", e.getHandle(hoT_), hcalMin_);

    // tracker clusters (closest thing to raw hits): global position of the cluster barycentre
    j.s << ",\"pixel\":[";
    if (auto h = e.getHandle(pixT_); h.isValid()) {
      bool first = true;
      for (const auto& ds : *h) {
        const GeomDetUnit* du = tkGeo.idToDetUnit(DetId(ds.detId()));
        auto top = du ? dynamic_cast<const PixelTopology*>(&du->topology()) : nullptr;
        if (!top) continue;
        for (const auto& cl : ds) {
          j.s << (first ? "" : ",");
          j.pt3(du->surface().toGlobal(top->localPosition(MeasurementPoint(cl.x(), cl.y()))));
          first = false;
        }
      }
    }
    j.s << ']';
    j.s << ",\"strip\":[";
    if (auto h = e.getHandle(strT_); h.isValid()) {
      bool first = true;
      for (const auto& ds : *h) {
        const GeomDetUnit* du = tkGeo.idToDetUnit(DetId(ds.detId()));
        auto top = du ? dynamic_cast<const StripTopology*>(&du->topology()) : nullptr;
        if (!top) continue;
        for (const auto& cl : ds) {
          j.s << (first ? "" : ",");
          j.pt3(du->surface().toGlobal(top->localPosition(cl.barycenter())));
          first = false;
        }
      }
    }
    j.s << ']';

    // muon system: segments as [centre, direction] and RPC/GEM hits as points
    auto segs = [&](const char* key, const auto& h) {
      j.s << ",\"" << key << "\":[";
      bool first = true;
      if (h.isValid())
        for (const auto& sg : *h) {
          const GeomDet* d = glGeo.idToDet(sg.geographicalId());
          if (!d) continue;
          const GlobalPoint p = d->surface().toGlobal(sg.localPosition());
          const GlobalVector v = d->surface().toGlobal(sg.localDirection());
          j.s << (first ? "[" : ",[");
          j.pt3(p);
          j.s << ",[";
          j.v(v.x()); j.s << ','; j.v(v.y()); j.s << ','; j.v(v.z());
          j.s << "]]";
          first = false;
        }
      j.s << ']';
    };
    segs("dt", e.getHandle(dtT_));
    segs("csc", e.getHandle(cscT_));
    auto hits = [&](const char* key, const auto& h) {
      j.s << ",\"" << key << "\":[";
      bool first = true;
      if (h.isValid())
        for (const auto& r : *h) {
          const GeomDet* d = glGeo.idToDet(r.geographicalId());
          if (!d) continue;
          j.s << (first ? "" : ",");
          j.pt3(d->surface().toGlobal(r.localPosition()));
          first = false;
        }
      j.s << ']';
    };
    hits("rpc", e.getHandle(rpcT_));
    hits("gem", e.getHandle(gemT_));
    j.s << "}\n";

    std::ofstream f(outDir_ + "/event_" + std::to_string(e.id().run()) + "_" + std::to_string(e.id().event()) + ".json");
    f << j.s.str();
  }

private:
  const std::string outDir_;
  const double ecalMin_, hcalMin_, hfMin_, trkPtMin_;
  const edm::EDGetTokenT<edm::TriggerResults> trigT_;
  const edm::EDGetTokenT<reco::TrackCollection> trkT_;
  const edm::EDGetTokenT<reco::VertexCollection> vtxT_;
  const edm::EDGetTokenT<reco::MuonCollection> muT_;
  const edm::EDGetTokenT<reco::GsfElectronCollection> eleT_;
  const edm::EDGetTokenT<reco::PhotonCollection> phoT_;
  const edm::EDGetTokenT<reco::PFJetCollection> jetT_;
  const edm::EDGetTokenT<reco::PFMETCollection> metT_;
  const edm::EDGetTokenT<EcalRecHitCollection> ebT_, eeT_;
  const edm::EDGetTokenT<HBHERecHitCollection> hbheT_;
  const edm::EDGetTokenT<HFRecHitCollection> hfT_;
  const edm::EDGetTokenT<HORecHitCollection> hoT_;
  const edm::EDGetTokenT<edmNew::DetSetVector<SiPixelCluster>> pixT_;
  const edm::EDGetTokenT<edmNew::DetSetVector<SiStripCluster>> strT_;
  const edm::EDGetTokenT<DTRecSegment4DCollection> dtT_;
  const edm::EDGetTokenT<CSCSegmentCollection> cscT_;
  const edm::EDGetTokenT<RPCRecHitCollection> rpcT_;
  const edm::EDGetTokenT<GEMRecHitCollection> gemT_;
  const edm::EDGetTokenT<reco::GenParticleCollection> genT_;
  const edm::ESGetToken<TrackerGeometry, TrackerDigiGeometryRecord> tkGeoT_;
  const edm::ESGetToken<GlobalTrackingGeometry, GlobalTrackingGeometryRecord> glGeoT_;
  const edm::ESGetToken<CaloGeometry, CaloGeometryRecord> caloGeoT_;
};

DEFINE_FWK_MODULE(RawVizDumper);
