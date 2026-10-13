from RawViz.EventDump.gen_common import pythia
# gg -> H(125) -> gamma gamma
generator, ProductionFilterSequence = pythia(['HiggsSM:gg2H = on', '25:m0 = 125.0', '25:onMode = off', '25:onIfMatch = 22 22'])
