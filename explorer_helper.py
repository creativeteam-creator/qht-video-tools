"""
QHT Explorer Helper — Windows pe chalao (ek baar)
Yeh ek local server hai jo Streamlit se request lekar
File Explorer mein file reveal karta hai.

Run karo: python explorer_helper.py
Ya: Start Explorer Helper.bat
"""

from http.server import HTTPServer, BaseHTTPRequestHandler
import subprocess
import urllib.parse
import sys

PORT = 9731


class ExplorerHandler(BaseHTTPRequestHandler):

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def do_OPTIONS(self):
        self.send_response(200)
        self._cors()
        self.end_headers()

    def do_GET(self):
        if self.path.startswith("/open?path="):
            raw = self.path[len("/open?path="):]
            path = urllib.parse.unquote(raw)

            try:
                # explorer /select,"path" — file highlight karta hai
                subprocess.Popen(
                    ["explorer", "/select,", path],
                    shell=False,
                )
                self.send_response(200)
                self._cors()
                self.end_headers()
                self.wfile.write(b"ok")
            except Exception as e:
                self.send_response(500)
                self._cors()
                self.end_headers()
                self.wfile.write(str(e).encode())

        elif self.path == "/ping":
            self.send_response(200)
            self._cors()
            self.end_headers()
            self.wfile.write(b"pong")

        else:
            self.send_response(404)
            self._cors()
            self.end_headers()

    def log_message(self, format, *args):
        # Clean log — sirf errors
        if "500" in args[0] if args else False:
            print(f"[ERROR] {args}")


def main():
    server = HTTPServer(("localhost", PORT), ExplorerHandler)
    print(f"QHT Explorer Helper chal raha hai — port {PORT}")
    print("Ab Streamlit mein 'Open in Explorer' button kaam karega.")
    print("Band karne ke liye: Ctrl+C\n")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nHelper band ho gaya.")
        sys.exit(0)


if __name__ == "__main__":
    main()
