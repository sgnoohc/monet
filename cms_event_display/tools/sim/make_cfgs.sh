#!/bin/bash
# cmsDriver configs for the simulated samples (RelVal 2024 settings, no pileup)
source /cvmfs/cms.cern.ch/cmsset_default.sh
cd /blue/avery/p.chang/work/cms_rawviz/CMSSW_14_0_25/src && eval `scram runtime -sh` && cd -
COMMON="--conditions auto:phase1_2024_realistic --era Run3_2024 --geometry DB:Extended --nThreads 8 --no_exec"
lumi=0
for spec in HZZ4L:hzz4l:24 HGG:hgg:12 TTbar:ttbar:12 ZLL:zll:12; do
  IFS=: read frag s n <<< "$spec"; lumi=$((lumi+1))
  cmsDriver.py RawViz/EventDump/python/${frag}_13p6TeV_cfi.py -s GEN,SIM $COMMON --beamspot DBrealistic \
    --datatier GEN-SIM --eventcontent RAWSIM -n $n --fileout file:${s}_gensim.root --python_filename ${s}_gensim_cfg.py \
    --customise_commands "process.source.firstLuminosityBlock=cms.untracked.uint32($lumi)\nprocess.RandomNumberGeneratorService.generator.initialSeed=$((1000+lumi))"
  cmsDriver.py step2 -s DIGI,L1,DIGI2RAW,HLT:@relval2024 $COMMON --datatier GEN-SIM-DIGI-RAW --eventcontent FEVTDEBUGHLT \
    --filein file:${s}_gensim.root --fileout file:${s}_raw.root -n -1 --python_filename ${s}_raw_cfg.py
  cmsDriver.py step3 -s RAW2DIGI,L1Reco,RECO $COMMON --datatier GEN-SIM-RECO --eventcontent RECOSIM \
    --filein file:${s}_raw.root --fileout file:${s}_reco.root -n -1 --python_filename ${s}_reco_cfg.py
  mkdir -p json_${s}
  cat >> ${s}_reco_cfg.py <<PY

process.rawViz = cms.EDAnalyzer('RawVizDumper', outDir=cms.string('json_${s}'), ecalMin=cms.double(0.3), hcalMin=cms.double(0.8), hfMin=cms.double(3.0), trackPtMin=cms.double(0.5))
process.rawViz_step = cms.EndPath(process.rawViz)
process.schedule.append(process.rawViz_step)
PY
done
