from RawViz.EventDump.gen_common import pythia
# q qbar -> Z -> ee or mumu
generator, ProductionFilterSequence = pythia(['WeakSingleBoson:ffbar2gmZ = on', 'WeakZ0:gmZmode = 2', 'PhaseSpace:mHatMin = 50.',
                                              '23:onMode = off', '23:onIfAny = 11 13'])
