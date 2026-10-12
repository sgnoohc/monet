import sys, re, collections
import ROOT
from DataFormats.FWLite import Events, Handle
f = sys.argv[1]; nmax = int(sys.argv[2]) if len(sys.argv) > 2 else 100000
ev = Events(f)
h = Handle('edm::TriggerResults')
want = re.compile(r'^HLT_(IsoMu24|Mu17_TrkIsoVVL_Mu8_TrkIsoVVL_DZ_Mass3p8|Mu37_TkMu27|Ele32_WPTight_Gsf|DoubleEle25_CaloIdL_MW|PFJet500|PFHT1050|AK8PFJet500|Mu50|DoubleMu4_3_LowMass|Photon200|Ele30_WPTight_Gsf|IsoMu24_eta2p1|Mu17_TrkIsoVVL_Ele23_CaloIdL_TrackIdL_IsoVL_DZ|Mu23_TrkIsoVVL_Ele12_CaloIdL_TrackIdL_IsoVL_DZ|DiPFJetAve500|PFMET120_PFMHT120_IDTight|TripleMu_12_10_5|DoubleMu3_Trk_Tau3mu)_v\d+$')
cnt = collections.Counter(); hits = []
for i, e in enumerate(ev):
    if i >= nmax: break
    e.getByLabel(('TriggerResults', '', 'HLT'), h)
    tr = h.product(); names = e.object().triggerNames(tr)
    passed = [names.triggerName(j) for j in range(tr.size()) if tr.accept(j) and want.match(names.triggerName(j))]
    for p in passed: cnt[re.sub(r'_v\d+$', '', p)] += 1
    if passed:
        a = e.eventAuxiliary()
        hits.append((i, a.run(), a.luminosityBlock(), a.event(), [re.sub(r'_v\d+$', '', p) for p in passed]))
print('scanned', i + 1)
for k, v in cnt.most_common(): print(f'{v:5d} {k}')
for x in hits: print(x)
