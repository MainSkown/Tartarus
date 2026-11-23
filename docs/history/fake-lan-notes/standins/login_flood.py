import sys, time, multiprocessing as mp
from impacket.smbconnection import SMBConnection
host, total, procs = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
def work(n):
    ok = fail = 0
    for i in range(n):
        try:
            c = SMBConnection(host, host, sess_port=445, timeout=5)
            c.login(f"user{i}", "pw", "CORP"); ok += 1; c.logoff()
        except Exception: fail += 1
    return ok, fail
if __name__ == "__main__":
    t = time.time()
    with mp.Pool(procs) as p: res = p.map(work, [total // procs] * procs)
    dt = time.time() - t; ok = sum(r[0] for r in res); fail = sum(r[1] for r in res)
    print(f"attempts={total} ok={ok} fail={fail} seconds={dt:.1f} rate={total/dt:.0f}/s")
