import itb.leaders as leaders


class VT:
    def __init__(self):
        self.t = 5_000.0

    def time(self):
        return self.t

    def sleep(self, d):
        self.t += d


def _clock(monkeypatch, slot_s_true=0.2143):
    vt = VT()
    monkeypatch.setattr(leaders, "time", vt)
    t0 = vt.t

    class R:
        def call(self, method, params=None):
            return 100 + int((vt.t - t0) / slot_s_true)

    return vt, leaders.SlotClock(R())


def test_initial_slot_time_and_refit_needs_five_seconds(monkeypatch):
    vt, c = _clock(monkeypatch, slot_s_true=0.25)
    assert c.slot_s == 0.2143
    c.sync(); vt.sleep(2.0); c.sync(); vt.sleep(2.0); c.sync()     # spans 4 s: no refit
    assert c.slot_s == 0.2143
    vt.sleep(2.0); c.sync()                                          # spans 6 s: refit
    assert abs(c.slot_s - 0.25) < 0.01


def test_sync_is_rate_limited_to_about_one_call_per_second(monkeypatch):
    vt, c = _clock(monkeypatch)
    for _ in range(10):
        c.sync()
    assert c.n_calls == 1
    vt.sleep(1.0); c.sync()
    assert c.n_calls == 2
    vt.sleep(0.5); s = c.sync()                                      # cached estimate, no call
    assert c.n_calls == 2 and isinstance(s, int)
