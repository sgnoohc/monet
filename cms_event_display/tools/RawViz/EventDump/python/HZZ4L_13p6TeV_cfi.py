from RawViz.EventDump.gen_common import pythia
# gg -> H(125) -> ZZ* -> 4l, l = e or mu
generator, ProductionFilterSequence = pythia(['HiggsSM:gg2H = on', '25:m0 = 125.0', '25:onMode = off', '25:onIfMatch = 23 23',
                                              '23:onMode = off', '23:onIfAny = 11 13'])
