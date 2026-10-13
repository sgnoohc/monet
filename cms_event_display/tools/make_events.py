"""Build events/ for the page from RawVizDumper output.

    python3 tools/make_events.py --out events \
        --data json/ event_times.json \
        --sim hzz4l json_hzz4l/ 7,12 --sim hgg json_hgg/ 3 ...

--data: the dumper's JSON for recorded events, and event_times.json, which maps each
event number to {run, lumi, bx, orbit, time} read from the RAW file's EventAuxiliary.
--sim: a simulated sample name (see SAMPLES), its dumper JSON, and the event numbers to keep.
Writes one compact JSON per event, with source fields added, and index.json for the picker.
"""
import argparse, glob, json, math, os, re

DATA_SOURCE = {   # recorded events carry no 'kind'; the page treats a missing kind as data
    'dataset': '/EphemeralHLTPhysics0/Run2024F-v1/RAW',
    'file': 'root://eospublic.cern.ch//eos/opendata/cms/Run2024F/EphemeralHLTPhysics0/RAW/v1/000/383/631/00000/3d004fa8-9386-49c5-b043-99dff29500d8.root',
    'cmssw': 'CMSSW_14_0_25', 'steps': 'RAW2DIGI,L1Reco,RECO', 'era': 'Run3_2024', 'gt': '140X_dataRun3_Prompt_frozen_v4',
}
SIM_SOURCE = {
    'kind': 'sim', 'generator': 'Pythia 8, CP5 tune, √s = 13.6 TeV',
    'cmssw': 'CMSSW_14_0_25', 'steps': ['GEN,SIM', 'DIGI,L1,DIGI2RAW,HLT:2024v14', 'RAW2DIGI,L1Reco,RECO'],
    'era': 'Run3_2024', 'gt': '140X_mcRun3_2024_realistic_v26',
}
# Simulated samples: the generated process as the Sample row describes it (fragments in RawViz/EventDump/python)
SAMPLES = {
    'hzz4l': 'gg → H(125) → ZZ* → 4ℓ with ℓ = e or μ',
    'hgg': 'gg → H(125) → γγ',
    'ttbar': 'tt̄ with m(t) = 172.5 GeV, W → quarks, e or μ',
    'zll': 'qq̄ → Z → ee or μμ',
}
# Recorded events are listed under the first of these triggers they fired; the order sets the picker order.
KEY = ['HLT_TripleMu_12_10_5', 'HLT_PFJet500', 'HLT_PFMET120_PFMHT120_IDTight', 'HLT_IsoMu24', 'HLT_Ele32_WPTight_Gsf']
# Paths highlighted in the HLT list (the selection used by scan_hlt.py, plus diphoton and dielectron)
WANT = re.compile(r'^HLT_(IsoMu24|Mu17_TrkIsoVVL_Mu8_TrkIsoVVL_DZ_Mass3p8|Mu37_TkMu27|Ele32_WPTight_Gsf|DoubleEle25_CaloIdL_MW|PFJet500|PFHT1050|AK8PFJet500'
                  r'|Mu50|DoubleMu4_3_LowMass|Photon200|Ele30_WPTight_Gsf|IsoMu24_eta2p1|PFMET120_PFMHT120_IDTight|TripleMu_12_10_5|TripleMu_10_5_5_DZ'
                  r'|TripleMu_5_3_3_Mass3p8_DZ|Diphoton30_22_R9Id_OR_IsoCaloId_AND_HE_R9Id_Mass90|Ele23_Ele12_CaloIdL_TrackIdL_IsoVL)_v\d+$')
NOTE = {994851190: 'The two μ⁺ sit inside the 57 and 76 GeV jets; the leading μ⁺ heads straight into the cutaway.'}
LEP = {11: 'e', 13: 'μ'}


def mjj(a, b):
    p = [sum(x) for x in zip(*[(j['e'], j['pt'] * math.cos(j['phi']), j['pt'] * math.sin(j['phi']), j['pt'] * math.sinh(j['eta'])) for j in (a, b)])]
    return math.sqrt(max(0.0, p[0] ** 2 - p[1] ** 2 - p[2] ** 2 - p[3] ** 2))


def data_label(d, key):
    by_pt = lambda xs: sorted(xs, key=lambda x: -x['pt'])
    mu, el, jets, met = by_pt(d['muons']), by_pt(d['electrons']), by_pt(d['jets']), d['met']['pt']
    gev = lambda xs: ', '.join(f"{x['pt']:.0f}" for x in xs) + ' GeV'
    if key == 'HLT_TripleMu_12_10_5':
        return f'{len(mu)} muons, {gev(mu)}'
    if key == 'HLT_PFJet500':
        return f"Jets {gev([j for j in jets[:3] if j['pt'] >= 100])}, m(j1 j2) {mjj(jets[0], jets[1]) / 1000:.2f} TeV"
    if key == 'HLT_PFMET120_PFMHT120_IDTight':
        return f'Missing pT {met:.0f} GeV, leading jet {jets[0]["pt"]:.0f} GeV'
    if key == 'HLT_IsoMu24':
        return f'Muon {mu[0]["pt"]:.0f} GeV, missing pT {met:.0f} GeV'
    return f'Electron {el[0]["pt"]:.0f} GeV, missing pT {met:.0f} GeV'


def sim_truth(sample, gen):
    """(menu label, decay chain, generator-level note) from the hard-process particles."""
    out = [p for p in gen if p['st'] != 22]     # outgoing: status 23, or 1 when the particle was never re-copied; 22 marks resonances
    leps = [p for p in out if abs(p['id']) in LEP]
    flav = lambda ps: ''.join(sorted(LEP[abs(p['id'])] for p in ps))
    if sample == 'hzz4l':
        n = {f: sum(LEP[abs(p['id'])] == f for p in leps) for f in 'eμ'}
        chan = '4μ' if n['μ'] == 4 else '4e' if n['e'] == 4 else '2e2μ'
        zs = sorted((p['m'] for p in gen if p['id'] == 23), reverse=True)
        return f'H → ZZ* → {chan}', f'gg → H → ZZ* → {chan}', f'Generator level: m(Z₁) = {zs[0]:.1f} GeV, m(Z₂) = {zs[1]:.1f} GeV.'
    if sample == 'hgg':
        g = sorted((p['pt'] for p in out if p['id'] == 22), reverse=True)
        return 'H → γγ', 'gg → H → γγ', f'Generator level: photons with pT {g[0]:.1f} and {g[1]:.1f} GeV.'
    if sample == 'ttbar':
        wl = [LEP[abs(p['id'])] for p in leps if abs(p['mo']) == 24]
        tops = [p for p in gen if abs(p['id']) == 6][:2]
        v = [sum(x) for x in zip(*[(math.hypot(p['pt'] * math.cosh(p['eta']), p['m']), p['pt'] * math.cos(p['phi']), p['pt'] * math.sin(p['phi']), p['pt'] * math.sinh(p['eta'])) for p in tops])]
        mtt = math.sqrt(max(0.0, v[0] ** 2 - v[1] ** 2 - v[2] ** 2 - v[3] ** 2))
        chan = 'all-hadronic' if not wl else f'lepton+jets, W → {wl[0]}ν' if len(wl) == 1 else f'dilepton, W → {wl[0]}ν and {wl[1]}ν'
        return f'tt̄, {chan}', f'tt̄ → bW⁺ b̄W⁻, {chan}', f'Generator level: m(tt̄) = {mtt:.0f} GeV.'
    z = next(p for p in gen if p['id'] == 23)
    pair = {'ee': 'e⁺e⁻', 'μμ': 'μ⁺μ⁻'}[flav(leps)]
    return f'Z → {flav(leps)}', f'qq̄ → Z → {pair}', f'Generator level: m(Z) = {z["m"]:.1f} GeV.'


def write(d, out, name):
    json.dump(d, open(os.path.join(out, name), 'w'), separators=(',', ':'), ensure_ascii=False)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', required=True)
    ap.add_argument('--data', nargs=2, metavar=('JSON_DIR', 'TIMES'))
    ap.add_argument('--sim', nargs=3, action='append', default=[], metavar=('SAMPLE', 'JSON_DIR', 'EVENTS'))
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    rows = []
    if a.data:
        T = json.load(open(a.data[1]))
        for f in glob.glob(os.path.join(a.data[0], 'event_*.json')):
            d = json.load(open(f))
            t = T[str(d['event'])]
            d.update(time=t['time'], bx=t['bx'], orbit=t['orbit'], source=DATA_SOURCE)
            fired = [re.sub(r'_v\d+$', '', h) for h in d['hlt']]
            key = next(k for k in KEY if k in fired)
            write(d, a.out, f"{d['event']}.json")
            row = dict(id=str(d['event']), kind='data', event=d['event'], run=d['run'], lumi=d['lumi'], file=f"{d['event']}.json",
                       key=key, label=data_label(d, key), keys=[h for h in d['hlt'] if WANT.match(h)])
            if d['event'] in NOTE:
                row['note'] = NOTE[d['event']]
            rows.append(row)
        rows.sort(key=lambda r: (KEY.index(r['key']), r['event']))
    for sample, src, picks in a.sim:
        for ev in picks.split(','):
            f, = glob.glob(os.path.join(src, f'event_*_{ev}.json'))
            d = json.load(open(f))
            d['source'] = SIM_SOURCE
            label, truth, note = sim_truth(sample, d['gen'])
            name = f'sim_{sample}_{ev}.json'
            write(d, a.out, name)
            rows.append(dict(id=f'sim-{sample}-{ev}', kind='sim', event=d['event'], run=d['run'], lumi=d['lumi'], file=name,
                             label=label, truth=truth, sample=SAMPLES[sample], note=note, photons=sample == 'hgg',
                             keys=[h for h in d['hlt'] if WANT.match(h)]))
    json.dump(rows, open(os.path.join(a.out, 'index.json'), 'w'), indent=1, ensure_ascii=False)
    for r in rows:
        print(r['id'], '|', r['label'])


if __name__ == '__main__':
    main()
