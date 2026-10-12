# Re-run only the JSON dumper on the RECO output (geometry and conditions as in reco_cfg.py)
import FWCore.ParameterSet.Config as cms
from Configuration.Eras.Era_Run3_2024_cff import Run3_2024
process = cms.Process('DUMP', Run3_2024)
process.load('Configuration.StandardSequences.Services_cff')
process.load('FWCore.MessageService.MessageLogger_cfi')
process.load('Configuration.StandardSequences.GeometryRecoDB_cff')
process.load('Configuration.StandardSequences.MagneticField_cff')
process.load('Configuration.StandardSequences.FrontierConditions_GlobalTag_cff')
from Configuration.AlCa.GlobalTag import GlobalTag
process.GlobalTag = GlobalTag(process.GlobalTag, 'auto:run3_data_prompt', '')
process.source = cms.Source('PoolSource', fileNames=cms.untracked.vstring('file:reco.root'))
process.maxEvents = cms.untracked.PSet(input=cms.untracked.int32(-1))
process.MessageLogger.cerr.FwkReport.reportEvery = 1
process.rawViz = cms.EDAnalyzer('RawVizDumper',
    outDir=cms.string('json'), ecalMin=cms.double(0.3), hcalMin=cms.double(0.8), hfMin=cms.double(3.0), trackPtMin=cms.double(0.5))
process.p = cms.EndPath(process.rawViz)
