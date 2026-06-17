# Captive-portal setup server for the GitHub Universe badge.
#
# Performance notes: fully non-blocking — poll() is called once per frame and
# returns immediately when there's nothing to do. The listening sockets are
# non-blocking; an accepted client is handled with a short timeout so a slow
# phone can't stall the badge's render loop for more than ~1.5s in the worst
# case (requests are rare during setup). No allocation in the idle path.
import network
import socket
import time

AP_IP = "192.168.4.1"


def _dns_reply(query, ip):
    # minimal DNS hijack: point A queries at our AP IP. For AAAA (IPv6) and other
    # types, return NODATA so phones (esp. Android, which does IPv6 lookups for
    # its captive probes) cleanly fall back to the A record instead of getting a
    # type-mismatched answer that breaks detection.
    if len(query) < 12:
        return None
    q = query[12:]
    i = 0
    while i < len(q) and q[i] != 0:
        i += q[i] + 1
    qend = i + 1 + 4                      # null byte + QTYPE(2) + QCLASS(2)
    qtype = ((q[i + 1] << 8) | q[i + 2]) if (i + 2) < len(q) else 1
    if qtype != 1:                       # not an A record -> NODATA (ANCOUNT 0)
        return query[:2] + b"\x81\x80\x00\x01\x00\x00\x00\x00\x00\x00" + q[:qend]
    header = query[:2] + b"\x81\x80\x00\x01\x00\x01\x00\x00\x00\x00"
    ipb = bytes(int(x) for x in ip.split("."))
    answer = b"\xc0\x0c\x00\x01\x00\x01\x00\x00\x00\x1e\x00\x04" + ipb
    return header + q[:qend] + answer


def _dns_name(query):
    try:
        q = query[12:]
        out = []
        i = 0
        while i < len(q) and q[i] != 0:
            out.append(q[i + 1:i + 1 + q[i]].decode("latin1"))
            i += q[i] + 1
        return ".".join(out)
    except Exception:
        return "?"


def _dns_qtype(query):
    try:
        q = query[12:]
        i = 0
        while i < len(q) and q[i] != 0:
            i += q[i] + 1
        return (q[i + 1] << 8) | q[i + 2]
    except Exception:
        return 0


def _urldecode(s):
    s = s.replace("+", " ")
    out = ""
    i = 0
    while i < len(s):
        c = s[i]
        if c == "%" and i + 2 < len(s):
            try:
                out += chr(int(s[i + 1:i + 3], 16))
                i += 3
                continue
            except ValueError:
                pass
        out += c
        i += 1
    return out


def parse_form(body):
    data = {}
    for pair in body.split("&"):
        if not pair:
            continue
        k, _, v = pair.partition("=")
        data[_urldecode(k)] = _urldecode(v)
    return data


class Portal:
    def __init__(self, ssid, password, on_save, page_bytes=b""):
        self.ssid = ssid
        self.password = password
        self.page = page_bytes              # full HTML (already templated) as bytes
        self.on_save = on_save              # callback(dict) -> None
        self.ap = None
        self.http = None
        self.dns = None
        self.clients = 0
        self.saved = False
        try:                              # diagnostics on only when this flag exists
            open("/portal_debug").close()
            self._debug = True
        except OSError:
            self._debug = False
        self._log = []
        self._flush = 0

    def _logadd(self, s):
        if not self._debug:
            return
        self._log.append(s)
        if len(self._log) > 300:
            self._log = self._log[-250:]

    def _logflush(self):
        if not self._debug or not self._log:
            return
        try:
            with open("/portal_log.txt", "w") as f:
                f.write("\n".join(self._log[-250:]))
        except Exception:
            pass

    def start_ap(self):
        # bring the hotspot up FIRST so it broadcasts the instant Setup opens
        try:
            network.country("US")           # proper 2.4GHz regulatory/channels
        except Exception:
            pass
        self.ap = network.WLAN(network.AP_IF)
        if self.password:
            self.ap.config(essid=self.ssid, password=self.password, security=4)
        else:
            self.ap.config(essid=self.ssid, security=0)
        self.ap.active(True)
        t = time.ticks_ms()
        while not self.ap.active() and time.ticks_diff(time.ticks_ms(), t) < 3000:
            time.sleep_ms(100)

    def start_http(self, page_bytes=None):
        if page_bytes is not None:
            self.page = page_bytes
        self.http = socket.socket()
        self.http.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.http.bind(("0.0.0.0", 80))
        self.http.listen(4)
        self.http.setblocking(False)
        self.dns = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.dns.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.dns.bind(("0.0.0.0", 53))
        self.dns.setblocking(False)
        self._logadd("== portal up: AP=%s ip=%s ==" % (self.ssid, AP_IP))

    def start(self):                        # convenience: AP + servers together
        self.start_ap()
        self.start_http()

    def stop(self):
        for s in (self.http, self.dns):
            try:
                if s:
                    s.close()
            except Exception:
                pass
        try:
            if self.ap:
                self.ap.active(False)
        except Exception:
            pass

    def num_clients(self):
        try:
            return len(self.ap.status("stations"))
        except Exception:
            return 0

    def poll(self):
        # Drain bursts: a phone joining fires SEVERAL DNS lookups + captive-probe
        # requests back-to-back. Handling only one per frame makes captive
        # detection slow and flaky (the "had to tap Join several times" symptom)
        # and can delay the form POST. Drain a bounded batch each frame instead.
        for _ in range(16):
            if not self._poll_dns():
                break
        for _ in range(6):
            if not self._poll_http():
                break
        self._flush += 1
        if self._flush >= 20:            # persist the diagnostic log ~once a second
            self._flush = 0
            self._logflush()

    def _poll_dns(self):
        try:
            data, addr = self.dns.recvfrom(256)
        except OSError:
            return False
        self._logadd("DNS %-4s %s" % ({1: "A", 28: "AAAA", 65: "HTTPS"}.get(_dns_qtype(data), str(_dns_qtype(data))), _dns_name(data)))
        r = _dns_reply(data, AP_IP)
        if r:
            try:
                self.dns.sendto(r, addr)
            except OSError:
                pass
        return True

    def _poll_http(self):
        try:
            cl, addr = self.http.accept()
        except OSError:
            return False
        try:
            cl.settimeout(1.0)
            req = b""
            while b"\r\n\r\n" not in req and len(req) < 4096:
                chunk = cl.recv(512)
                if not chunk:
                    break
                req += chunk
            head, _, rest = req.partition(b"\r\n\r\n")
            line0 = head.split(b"\r\n", 1)[0]
            parts = line0.split(b" ")
            method = parts[0] if parts else b"GET"
            path = parts[1] if len(parts) > 1 else b"/"
            host = b""
            for ln in head.split(b"\r\n"):
                if ln[:5].lower() == b"host:":
                    host = ln[5:].strip()
                    break
            self._logadd("HTTP %s %s%s" % (method.decode("latin1", "replace"),
                                           host.decode("latin1", "replace"),
                                           path.decode("latin1", "replace")))
            if method == b"POST" and path.startswith(b"/save"):
                clen = 0
                for ln in head.split(b"\r\n"):
                    if ln.lower().startswith(b"content-length:"):
                        try:
                            clen = int(ln.split(b":", 1)[1].strip())
                        except ValueError:
                            clen = 0
                body = rest
                while len(body) < clen:
                    chunk = cl.recv(512)
                    if not chunk:
                        break
                    body += chunk
                form = parse_form(body.decode("utf-8", "replace"))
                ok = True
                err = ""
                try:
                    self.on_save(form)
                except Exception as e:  # noqa: BLE001
                    ok = False
                    err = str(e)
                    print("save error", e)
                self.saved = ok
                self._send(cl, _success_page(ok, err))
            elif path == b"/" or path.startswith(b"/?") or path.startswith(b"/save"):
                self._send(cl, self.page)
            else:
                # Captive-portal probe (Android /generate_204, iOS
                # /hotspot-detect.html, Windows /ncsi.txt, ...). A 302 to the
                # portal root reliably triggers the OS sign-in flow: Android
                # only auto-opens the login page on a REDIRECT — a 200 leaves it
                # "connected, no internet" with no page (the Samsung symptom).
                # iOS follows the redirect to the same page, so it still works.
                self._send_redirect(cl, "http://" + AP_IP + "/")
        except Exception as e:  # noqa: BLE001
            print("http err", e)
        finally:
            try:
                cl.close()
            except Exception:
                pass
        return True

    def _send(self, cl, body):
        if isinstance(body, str):
            body = body.encode()
        hdr = ("HTTP/1.1 200 OK\r\nContent-Type:text/html;charset=utf-8\r\n"
               "Content-Length:%d\r\nCache-Control:no-store\r\n"
               "Connection:close\r\n\r\n" % len(body))
        try:
            cl.sendall(hdr.encode() + body)
        except OSError:
            pass

    def _send_redirect(self, cl, url):
        body = ('<!doctype html><meta http-equiv=refresh content="0;url=%s">'
                '<a href="%s">Set up your badge</a>' % (url, url)).encode()
        hdr = ("HTTP/1.1 302 Found\r\nLocation: %s\r\n"
               "Content-Type:text/html;charset=utf-8\r\nContent-Length:%d\r\n"
               "Cache-Control:no-store\r\nConnection:close\r\n\r\n" % (url, len(body)))
        try:
            cl.sendall(hdr.encode() + body)
        except OSError:
            pass


def _success_page(ok, err=""):
    if ok:
        msg = ("<h1>&#10003; Saved!</h1><p>Your badge is configured. "
               "You can close this page &mdash; the badge will connect now.</p>")
        col = "#3fb950"
    elif "pin" in err.lower():
        msg = ("<h1>Wrong PIN</h1><p>Check the 4-digit code shown on your "
               "badge screen and enter it again.</p>")
        col = "#f85149"
    else:
        msg = ("<h1>Hmm, that didn't save</h1><p>Go back and try again.</p>")
        col = "#f85149"
    return ("<!doctype html><meta name=viewport content='width=device-width,"
            "initial-scale=1'><style>body{margin:0;font-family:-apple-system,"
            "Segoe UI,Roboto,sans-serif;background:#0d1117;color:#e9eef5;"
            "display:flex;min-height:100vh;align-items:center;justify-content:"
            "center;text-align:center;padding:24px}h1{color:%s}p{color:#9aa4b0;"
            "line-height:1.6}</style><div>%s</div>" % (col, msg))
