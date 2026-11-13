"""Test double: an S3 endpoint that rejects every request with 403 InvalidAccessKeyId.

s3mock accepts any credentials, so the "the key was rotated/deleted" path needs a
server that behaves like S3 does when the key is unknown. This is a simulation, not
AWS: it exists so the failure handling can be tested without touching real keys.
"""
import http.server

BODY = (b'<?xml version="1.0" encoding="UTF-8"?>'
        b"<Error><Code>InvalidAccessKeyId</Code>"
        b"<Message>The AWS Access Key Id you provided does not exist in our records.</Message>"
        b"<AWSAccessKeyId>AKIAWRONGKEY000000</AWSAccessKeyId></Error>")


class Denied(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _deny(self):
        self.send_response(403)
        self.send_header("Content-Type", "application/xml")
        self.send_header("Content-Length", str(len(BODY)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(BODY)

    do_GET = do_PUT = do_POST = do_DELETE = do_HEAD = _deny

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    http.server.ThreadingHTTPServer(("0.0.0.0", 9000), Denied).serve_forever()
