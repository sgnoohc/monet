# Pythia 8 with the CP5 tune at 13.6 TeV; each fragment below sets its own process
import FWCore.ParameterSet.Config as cms
from Configuration.Generator.Pythia8CommonSettings_cfi import *
from Configuration.Generator.MCTunesRun3ECM13p6TeV.PythiaCP5Settings_cfi import *

def pythia(process):
    gen = cms.EDFilter("Pythia8ConcurrentGeneratorFilter",
        pythiaHepMCVerbosity=cms.untracked.bool(False), maxEventsToPrint=cms.untracked.int32(0),
        pythiaPylistVerbosity=cms.untracked.int32(0), filterEfficiency=cms.untracked.double(1.0),
        comEnergy=cms.double(13600.0),
        PythiaParameters=cms.PSet(pythia8CommonSettingsBlock, pythia8CP5SettingsBlock,
            processParameters=cms.vstring(*process),
            parameterSets=cms.vstring('pythia8CommonSettings', 'pythia8CP5Settings', 'processParameters')))
    return gen, cms.Sequence(gen)
