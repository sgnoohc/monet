#!/bin/bash
#SBATCH --job-name=rawviz_sim
#SBATCH --account=avery --qos=avery --partition=hpg-dev
#SBATCH --cpus-per-task=32 --mem=96gb --time=06:00:00
#SBATCH --output=/blue/avery/p.chang/work/cms_rawviz/sim/sim_%j.log
# GEN-SIM -> DIGI,L1,DIGI2RAW,HLT -> RAW2DIGI,L1Reco,RECO + RawVizDumper, the four samples in parallel
source /cvmfs/cms.cern.ch/cmsset_default.sh
cd /blue/avery/p.chang/work/cms_rawviz/CMSSW_14_0_25/src && eval $(scram runtime -sh)
cd /blue/avery/p.chang/work/cms_rawviz/sim
for s in hzz4l hgg ttbar zll; do
  ( for step in gensim raw reco; do
      echo "$(date +%T) $s $step start"
      cmsRun ${s}_${step}_cfg.py > ${s}_${step}.log 2>&1 || { echo "$(date +%T) $s $step FAILED"; exit 1; }
      echo "$(date +%T) $s $step done"
    done ) &
done
wait
echo "$(date +%T) all done"
