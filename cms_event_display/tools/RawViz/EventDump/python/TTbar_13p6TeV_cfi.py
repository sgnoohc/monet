from RawViz.EventDump.gen_common import pythia
# tt-bar, m_t = 172.5 GeV, W -> quarks, e or mu (no taus)
generator, ProductionFilterSequence = pythia(['Top:gg2ttbar = on', 'Top:qqbar2ttbar = on', '6:m0 = 172.5',
                                              '24:onMode = off', '24:onIfAny = 1 2 3 4 5 11 13'])
