# CMS Event Display

Eleven 2024 CMS Open Data collisions, reconstructed from the RAW data tier, and six simulated collisions, drawn inside the SketchUpCMS 3D detector model.

**View:** https://sgnoohc.github.io/monet/cms_event_display/

- **Events:** run 383631, lumis 415–416, recorded 2024-07-25. Pick one from the menu at the top or with ‹ ›. The URL hash names the event, so a link such as `#996449745` opens on it.

  | Event | Trigger | Content |
  |---|---|---|
  | 994851190 | `HLT_TripleMu_12_10_5` | 3 muons, 30, 16, 6 GeV (the default) |
  | 994324494 | `HLT_PFJet500` | jets 511, 250, 186 GeV |
  | 996449745 | `HLT_PFJet500` | jets 659 and 545 GeV, m(j1 j2) 1.55 TeV |
  | 993596241 | `HLT_PFMET120_PFMHT120_IDTight` | missing pT 153 GeV, leading jet 215 GeV |
  | 993827196, 994004254, 995013141, 996183500, 996202011 | `HLT_IsoMu24` | one muon, 27–47 GeV |
  | 994159267, 994603224 | `HLT_Ele32_WPTight_Gsf` | one electron, 42 GeV |

- **Simulated events** (marked CMS Simulation on the page), generated here with Pythia 8 (CP5, 13.6 TeV) and the full CMS simulation in CMSSW_14_0_25 with 2024 conditions, no pileup:

  | Hash | Process | Reconstructed |
  |---|---|---|
  | `sim-hzz4l-13` | gg → H → ZZ* → 4μ | m(4ℓ) 123.9 GeV |
  | `sim-hzz4l-6` | gg → H → ZZ* → 2e2μ | all four leptons |
  | `sim-hgg-8` | gg → H → γγ | m(γγ) 125.9 GeV |
  | `sim-ttbar-10` | tt̄, lepton+jets, W → μν | μ 31 GeV, 6 jets |
  | `sim-zll-2`, `sim-zll-5` | Z → μμ, Z → ee | both leptons |
- **Views:** 3D cutaway, transverse (r-φ), longitudinal (r-z). The detector can be drawn as Blueprint, Color or Glass, or turned off.
- **X-ray hits** draws hits hidden behind detector material at reduced brightness. **Replay collision** plays the event outward from the interaction point.
- **Event layers** turn each collection on or off. Sliders set the track pT and calorimeter energy thresholds. Strip clusters and HF hits start off because they wash out the tracks.
- **Layer style** sets, per layer: shape (box or circle), size, length scale, color, opacity and glow. Which of these apply depends on the layer: length scale is cm per GeV for calorimeter towers, stick length for muon segments, and a stretch factor for jets and missing pT. Styles are saved in the viewer's browser.

## Files

| File | What it is |
|---|---|
| `index.html` | The page (three.js r128 from CDN) |
| `events/` | One JSON per event, as written by `RawVizDumper`, plus the event time and source fields; `index.json` lists them for the picker |
| `cms_parts.js` | Detector geometry: the SketchUpCMS model ([CMS-OUTREACH-2019-002](https://cds.cern.ch/record/2677903)), packed as in [SketchUpCMS in Claude](https://claude.ai/artifact/Qm1yr7yEPr33qXEKVyLCFn) |
| `tools/RawViz/EventDump/plugins/` | CMSSW EDAnalyzer that writes one JSON per event |
| `tools/dump_cfg.py` | Runs only the dumper on a RECO file |
| `tools/scan_hlt.py` | FWLite scan of `TriggerResults` to pick events |
| `tools/make_events.py` | Builds `events/` from the dumper output, the event times and the chosen simulated events |
| `tools/RawViz/EventDump/python/` | Pythia 8 fragments for the simulated samples |
| `tools/sim/` | cmsDriver configs and the Slurm job for the simulation |

All lengths in the event files are in metres, in CMS global coordinates. The page maps CMS (x, y, z) to model (z, y, −x).

## Making the event

CMSSW_14_0_25 (`el9_amd64_gcc12`), with `tools/RawViz` copied to `$CMSSW_BASE/src/` and built with `scram b`.

1. **Pick events.** The source file is `/EphemeralHLTPhysics0/Run2024F-v1/RAW`:

       root://eospublic.cern.ch//eos/opendata/cms/Run2024F/EphemeralHLTPhysics0/RAW/v1/000/383/631/00000/3d004fa8-9386-49c5-b043-99dff29500d8.root

   Scan its HLT decisions with:

       python3 tools/scan_hlt.py <file>

2. **Copy the chosen events out of RAW:**

       edmCopyPickMerge inputFiles=<file> eventsToProcess=383631:994851190,... outputFile=raw_2024F_selected.root

3. **Reconstruct and dump.** Generate the RECO config, then append the `RawVizDumper` EndPath from `tools/dump_cfg.py` to it:

       cmsDriver.py reco -s RAW2DIGI,L1Reco,RECO --data --scenario pp --era Run3_2024 \
           --conditions auto:run3_data_prompt --eventcontent RECO --datatier RECO \
           --filein file:raw_2024F_selected.root --fileout file:reco.root -n -1 --no_exec

   `auto:run3_data_prompt` resolves to `140X_dataRun3_Prompt_frozen_v4` and needs Frontier access.

   To re-dump from an existing `reco.root`, run `cmsRun tools/dump_cfg.py` instead.

4. **Simulate** (optional). Copy `tools/RawViz/EventDump/python/` into the package too, rebuild, then run `tools/sim/make_cfgs.sh` and submit `tools/sim/run_sim.sh`. For each sample it runs GEN,SIM, then DIGI,L1,DIGI2RAW,HLT:@relval2024 (menu 2024v14), then RAW2DIGI,L1Reco,RECO with the dumper, using `auto:phase1_2024_realistic` (`140X_mcRun3_2024_realistic_v26`). The dumper also writes the generator's hard-process particles for simulated events.

5. **Build the page's event files:**

       python3 tools/make_events.py --out events --data json/ event_times.json \
           --sim hzz4l json_hzz4l/ 13,6 --sim hgg json_hgg/ 8 --sim ttbar json_ttbar/ 10 --sim zll json_zll/ 2,5

   `event_times.json` maps each event number to its run, lumi, bunch crossing, orbit and time, read from the RAW file's `EventAuxiliary`.

The dumper thresholds are:

- **Tracks:** highPurity, pT ≥ 0.5 GeV.
- **Calorimeter hits:** ECAL ≥ 0.3 GeV, HCAL ≥ 0.8 GeV, HF ≥ 3 GeV.
- **Objects:** electrons pT > 10 GeV, photons pT > 15 GeV, AK4 CHS jets pT > 30 GeV.

Tracks are drawn as helices in 3.8 T. Muon paths follow the inner-track helix to the coil, then the track extrapolation through each matched muon chamber, because DT hits measure only one coordinate. Between the coil and the first muon station, the drawn path is a smooth interpolation, not a measured track.

The SketchUpCMS model is approximate (2019 geometry), so reconstructed hit positions may not line up exactly with its surfaces.
