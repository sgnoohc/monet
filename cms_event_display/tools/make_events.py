"""Build events/ for the page from RawVizDumper output.

    python3 tools/make_events.py <dumper json dir> <event_times.json> <out dir>

event_times.json maps event number -> {run, lumi, bx, orbit, time}, as read from
the RAW file's EventAuxiliary. Writes one compact <event>.json per event, with the
time and source fields added, and index.json listing them for the event picker.
"""
import glob, json, math, os, re, sys

SOURCE = {
    'dataset': '/EphemeralHLTPhysics0/Run2024F-v1/RAW',
    'file': 'root://eospublic.cern.ch//eos/opendata/cms/Run2024F/EphemeralHLTPhysics0/RAW/v1/000/383/631/00000/3d004fa8-9386-49c5-b043-99dff29500d8.root',
    'cmssw': 'CMSSW_14_0_25', 'steps': 'RAW2DIGI,L1Reco,RECO', 'era': 'Run3_2024', 'gt': '140X_dataRun3_Prompt_frozen_v4',
}
# The trigger an event is listed under: the first of these it fired. Order sets the picker order.
KEY = ['HLT_TripleMu_12_10_5', 'HLT_PFJet500', 'HLT_PFMET120_PFMHT120_IDTight', 'HLT_IsoMu24', 'HLT_Ele32_WPTight_Gsf']
# Paths highlighted in the HLT list (the selection used by scan_hlt.py)
WANT = re.compile(r'^HLT_(IsoMu24|Mu17_TrkIsoVVL_Mu8_TrkIsoVVL_DZ_Mass3p8|Mu37_TkMu27|Ele32_WPTight_Gsf|DoubleEle25_CaloIdL_MW|PFJet500|PFHT1050|AK8PFJet500'
                  r'|Mu50|DoubleMu4_3_LowMass|Photon200|Ele30_WPTight_Gsf|IsoMu24_eta2p1|PFMET120_PFMHT120_IDTight|TripleMu_12_10_5|TripleMu_10_5_5_DZ'
                  r'|TripleMu_5_3_3_Mass3p8_DZ)_v\d+$')
NOTE = {994851190: 'The two μ⁺ sit inside the 57 and 76 GeV jets; the leading μ⁺ heads straight into the cutaway.'}


def mjj(a, b):
    p = [sum(x) for x in zip(*[(j['e'], j['pt'] * math.cos(j['phi']), j['pt'] * math.sin(j['phi']), j['pt'] * math.sinh(j['eta'])) for j in (a, b)])]
    return math.sqrt(max(0.0, p[0] ** 2 - p[1] ** 2 - p[2] ** 2 - p[3] ** 2))


def label(d, key):
    by_pt = lambda xs: sorted(xs, key=lambda x: -x['pt'])
    mu, el, jets, met = by_pt(d['muons']), by_pt(d['electrons']), by_pt(d['jets']), d['met']['pt']
    gev = lambda xs: ', '.join(f"{x['pt']:.0f}" for x in xs) + ' GeV'
    if key == 'HLT_TripleMu_12_10_5':
        return f'{len(mu)} muons, {gev(mu)}'
    if key == 'HLT_PFJet500':
        m = mjj(jets[0], jets[1])
        return f"Jets {gev([j for j in jets[:3] if j['pt'] >= 100])}, m(j1 j2) {m / 1000:.2f} TeV"
    if key == 'HLT_PFMET120_PFMHT120_IDTight':
        return f'Missing pT {met:.0f} GeV, leading jet {jets[0]["pt"]:.0f} GeV'
    if key == 'HLT_IsoMu24':
        return f'Muon {mu[0]["pt"]:.0f} GeV, missing pT {met:.0f} GeV'
    return f'Electron {el[0]["pt"]:.0f} GeV, missing pT {met:.0f} GeV'


def main(src, times, out):
    T = json.load(open(times))
    os.makedirs(out, exist_ok=True)
    rows = []
    for f in glob.glob(os.path.join(src, 'event_*.json')):
        d = json.load(open(f))
        t = T[str(d['event'])]
        d.update(time=t['time'], bx=t['bx'], orbit=t['orbit'], source=SOURCE)
        fired = [re.sub(r'_v\d+$', '', h) for h in d['hlt']]
        key = next(k for k in KEY if k in fired)
        name = f"{d['event']}.json"
        json.dump(d, open(os.path.join(out, name), 'w'), separators=(',', ':'), ensure_ascii=False)
        row = dict(event=d['event'], run=d['run'], lumi=d['lumi'], file=name, key=key, label=label(d, key),
                   keys=[h for h in d['hlt'] if WANT.match(h)])
        if d['event'] in NOTE:
            row['note'] = NOTE[d['event']]
        rows.append(row)
    rows.sort(key=lambda r: (KEY.index(r['key']), r['event']))
    json.dump(rows, open(os.path.join(out, 'index.json'), 'w'), indent=1, ensure_ascii=False)
    for r in rows:
        print(r['event'], r['key'], '|', r['label'])


if __name__ == '__main__':
    main(*sys.argv[1:4])
