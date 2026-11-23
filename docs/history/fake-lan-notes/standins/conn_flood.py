import socket, sys, time, threading
host, port, n, th = sys.argv[1], int(sys.argv[2]), int(sys.argv[3]), int(sys.argv[4])
def w(k):
    for _ in range(k):
        try: s = socket.create_connection((host, port), 3); s.close()
        except OSError: pass
t = time.time(); ts = [threading.Thread(target=w, args=(n // th,)) for _ in range(th)]
[x.start() for x in ts]; [x.join() for x in ts]; print(f"{port}: {n} connects in {time.time()-t:.1f}s")
