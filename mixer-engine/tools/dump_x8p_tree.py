#!/usr/bin/env python3
"""
Dump the FULL control tree from a UA Mixer Engine on TCP 4710
-> a raw tree capture for tools/tree_to_device_map.py  (for open-apollo #52).

The engine's `get /?recursive` only lists top-level child *names* (empty stubs), so we
walk the tree explicitly: get each node, read its children, recurse. This reproduces the
full `controls` tree (the x4 map is ~3.6 MB, so expect it to take a minute).

Run on the Mac (Apollo connected + UAD Console open, so UA Mixer Engine serves 4710):
    python3 dump_x8p_tree.py --host 127.0.0.1 --device-name "Apollo x8p"
Or from the LAN:
    python3 dump_x8p_tree.py --host <mac-ip> --device-name "Apollo Twin X"
"""
import socket, json, sys, time, argparse

class Engine:
    """Client for the engine's NUL-delimited JSON protocol on 4710.

    The receive buffer persists across reads: the engine routinely packs several
    messages into one TCP segment, and dropping whatever follows the first NUL
    silently loses replies — which shows up later as missing subtrees in the map.
    """

    def __init__(self, host, port, timeout=10):
        self.sock = socket.create_connection((host, port))
        self.sock.settimeout(timeout)
        self.buf = b""

    def recv_msg(self):
        """Read one null-terminated JSON message, keeping any trailing bytes."""
        while b"\x00" not in self.buf:
            chunk = self.sock.recv(65536)
            if not chunk:
                return None     # peer closed; any partial tail is unusable
            self.buf += chunk
        raw, self.buf = self.buf.split(b"\x00", 1)
        return json.loads(raw) if raw.strip() else None

    def get(self, path):
        self.sock.sendall(("get " + path + "\x00").encode("utf-8"))
        # skip any stray non-matching messages (e.g. meter updates), take the reply for `path`
        msg = None
        for _ in range(20):
            msg = self.recv_msg()
            if msg is None:
                return None
            if msg.get("path", "").rstrip("/") == path.rstrip("/"):
                return msg
        return msg

count = [0]
def walk(eng, path):
    resp = eng.get(path)
    if not resp:
        return {}
    data = resp.get("data", {})
    count[0] += 1
    if count[0] % 50 == 0:
        print(f"  ...{count[0]} nodes", file=sys.stderr)
    ch = data.get("children", {})
    for name in list(ch.keys()):
        child_path = path.rstrip("/") + "/" + name
        data["children"][name] = walk(eng, child_path)
    return data

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", required=True)
    ap.add_argument("--port", type=int, default=4710)
    ap.add_argument("--device-name", required=True,
                    help='model this capture came from, e.g. "Apollo x8p" — stamped '
                         "into the capture and used to name the device map")
    ap.add_argument("--out", help="output file (default: tree_<device_name>.json)")
    a = ap.parse_args()

    out_path = a.out or f"tree_{a.device_name.lower().replace(' ', '_')}.json"
    eng = Engine(a.host, a.port)
    print("connected — walking the full tree (can take ~1 min)...", file=sys.stderr)
    tree = walk(eng, "/")
    out = {
        "timestamp": int(time.time()), "host": a.host, "port": a.port,
        "tree_path": "/", "device_name": a.device_name, "controls": tree,
    }
    with open(out_path, "w") as fh:
        json.dump(out, fh, indent=1)
    kb = len(json.dumps(out)) // 1024
    print(f"wrote {out_path}: {count[0]} nodes, {kb} KB", file=sys.stderr)
    if kb < 100:
        print("!! still small — the tree may need auth/subscribe first; tell Claude the node count.", file=sys.stderr)

if __name__ == "__main__":
    main()
