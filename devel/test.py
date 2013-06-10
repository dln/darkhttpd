#!/usr/bin/env python
# This is run by the "cover" script.
import unittest
import socket
import signal
import re
import os
import random

WWWROOT = "tmp.httpd.tests"

class Conn:
    def __init__(self):
        self.port = 12346
        self.s = socket.socket()
        self.s.connect(("0.0.0.0", self.port))
        # connect throws socket.error on connection refused

    def get(self, url, http_ver="1.0", endl="\n", req_hdrs={}, method="GET"):
        req = method+" "+url
        if http_ver is not None:
            req += " HTTP/"+http_ver
        req += endl
        if http_ver is not None:
            req_hdrs["User-Agent"] = "test.py"
            req_hdrs["Connection"] = "close"
            for k,v in req_hdrs.items():
                req += k+": "+v+endl
        req += endl # end of request
        self.s.send(req)
        ret = ""
        while True:
            signal.alarm(1) # don't wait forever
            r = self.s.recv(65536)
            signal.alarm(0)
            if r == "":
                break
            else:
                ret += r
        return ret

def parse(resp):
    """
    Parse response into status line, headers and body.
    """
    pos = resp.index("\r\n\r\n") # throws exception on failure
    head = resp[:pos]
    body = resp[pos+4:]
    status,head = head.split("\r\n", 1)
    hdrs = {}
    for line in head.split("\r\n"):
        k, v = line.split(": ", 1)
        hdrs[k] = v
    return (status, hdrs, body)

class TestHelper(unittest.TestCase):
    def assertContains(self, body, *strings):
        for s in strings:
            self.assertTrue(s in body,
                            msg="expected %s in %s"%(repr(s), repr(body)))

    def assertIsIndex(self, body, path):
        self.assertContains(body,
            "<title>%s</title>\n"%path,
            "<h1>%s</h1>\n"%path,
            '<a href="..">..</a>/',
            'Generated by darkhttpd')

    def assertIsInvalid(self, body, path):
        self.assertContains(body,
            "<title>400 Bad Request</title>",
            "<h1>Bad Request</h1>\n",
            "You requested an invalid URL: %s\n"%path,
            'Generated by darkhttpd')

    def drive_range(self, range_in, range_out, len_out, data_out,
            status_out = "206 Partial Content"):
        resp = Conn().get(self.url, req_hdrs = {"Range": "bytes="+range_in})
        status, hdrs, body = parse(resp)
        self.assertContains(status, status_out)
        self.assertEquals(hdrs["Accept-Ranges"], "bytes")
        self.assertEquals(hdrs["Content-Range"], "bytes "+range_out)
        self.assertEquals(hdrs["Content-Length"], str(len_out))
        self.assertEquals(body, data_out)

class TestDirList(TestHelper):
    def setUp(self):
        self.fn = WWWROOT+"/escape#this"
        open(self.fn, "w").write("x"*12345)

    def tearDown(self):
        os.unlink(self.fn)

    def test_dirlist_escape(self):
        resp = Conn().get("/")
        status, hdrs, body = parse(resp)
        self.assertEquals(ord("#"), 0x23)
        self.assertContains(body, "escape%23this", "12345")

class TestCases(TestHelper):
    pass # these get autogenerated in setUpModule()

def nerf(s):
    return re.sub("[^a-zA-Z0-9]", "_", s)

def makeCase(name, url, hdr_checker=None, body_checker=None,
             req_hdrs={"User-Agent": "test.py"},
             http_ver=None, endl="\n"):
    def do_test(self):
        resp = Conn().get(url, http_ver, endl, req_hdrs)
        if http_ver is None:
            status = ""
            hdrs = {}
            body = resp
        else:
            status, hdrs, body = parse(resp)

        if hdr_checker is not None and http_ver is not None:
            hdr_checker(self, hdrs)

        if body_checker is not None:
            body_checker(self, body)

        # FIXME: check status
        if http_ver is not None:
            prefix = "HTTP/1.1 " # should 1.0 stay 1.0?
            self.assertTrue(status.startswith(prefix),
                msg="%s at start of %s"%(repr(prefix), repr(status)))

    v = http_ver
    if v is None:
        v = "0.9"
    test_name = "_".join([
        "test",
        nerf(name),
        nerf("HTTP"+v),
        {"\n":"LF", "\r\n":"CRLF"}[endl],
    ])
    do_test.__name__ = test_name # hax
    setattr(TestCases, test_name, do_test)

def makeCases(name, url, hdr_checker=None, body_checker=None,
              req_hdrs={"User-Agent": "test.py"}):
    for http_ver in [None, "1.0", "1.1"]:
        for endl in ["\n", "\r\n"]:
            makeCase(name, url, hdr_checker, body_checker,
                     req_hdrs, http_ver, endl)

def makeSimpleCases(name, url, assert_name):
    makeCases(name, url, None,
        lambda self,body: getattr(self, assert_name)(body, url))

def setUpModule():
    for args in [
        ["index",                "/",               "assertIsIndex"],
        ["up dir",               "/dir/../",        "assertIsIndex"],
        ["extra slashes",        "//dir///..////",  "assertIsIndex"],
        ["no trailing slash",    "/dir/..",         "assertIsIndex"],
        ["no leading slash",     "dir/../",         "assertIsInvalid"],
        ["invalid up dir",       "/../",            "assertIsInvalid"],
        ["fancy invalid up dir", "/./dir/./../../", "assertIsInvalid"],
        ]:
        makeSimpleCases(*args)

class TestDirRedirect(TestHelper):
    def setUp(self):
        self.url = "/mydir"
        self.fn = WWWROOT + self.url
        os.mkdir(self.fn)

    def tearDown(self):
        os.rmdir(self.fn)

    def test_dir_redirect(self):
        resp = Conn().get(self.url)
        status, hdrs, body = parse(resp)
        self.assertContains(status, "301 Moved Permanently")
        self.assertEquals(hdrs["Location"], self.url+"/") # trailing slash

class TestFileGet(TestHelper):
    def setUp(self):
        self.datalen = 2345
        self.data = "".join(
            [chr(random.randint(0,255)) for _ in xrange(self.datalen)])
        self.url = "/data.jpeg"
        self.fn = WWWROOT + self.url
        open(self.fn, "w").write(self.data)

    def tearDown(self):
        os.unlink(self.fn)

    def test_file_get(self):
        resp = Conn().get(self.url)
        status, hdrs, body = parse(resp)
        self.assertContains(status, "200 OK")
        self.assertEquals(hdrs["Accept-Ranges"], "bytes")
        self.assertEquals(hdrs["Content-Length"], str(self.datalen))
        self.assertEquals(hdrs["Content-Type"], "image/jpeg")
        self.assertContains(hdrs["Server"], "darkhttpd/")
        self.assertEquals(body, self.data)

    def test_file_head(self):
        resp = Conn().get(self.url, method="HEAD")
        status, hdrs, body = parse(resp)
        self.assertContains(status, "200 OK")
        self.assertEquals(hdrs["Accept-Ranges"], "bytes")
        self.assertEquals(hdrs["Content-Length"], str(self.datalen))
        self.assertEquals(hdrs["Content-Type"], "image/jpeg")

    def test_if_modified_since(self):
        resp1 = Conn().get(self.url, method="HEAD")
        status, hdrs, body = parse(resp1)
        lastmod = hdrs["Last-Modified"]

        resp2 = Conn().get(self.url, method="GET", req_hdrs =
            {"If-Modified-Since": lastmod })
        status, hdrs, body = parse(resp2)
        self.assertContains(status, "304 Not Modified")
        self.assertEquals(hdrs["Accept-Ranges"], "bytes")
        self.assertFalse(hdrs.has_key("Last-Modified"))
        self.assertFalse(hdrs.has_key("Content-Length"))
        self.assertFalse(hdrs.has_key("Content-Type"))

    def test_range_single(self):
        self.drive_range("5-5", "5-5/%d" % self.datalen,
            1, self.data[5])

    def test_range_single_first(self):
        self.drive_range("0-0", "0-0/%d" % self.datalen,
            1, self.data[0])

    def test_range_single_last(self):
        self.drive_range("%d-%d"%(self.datalen-1, self.datalen-1),
        "%d-%d/%d"%(self.datalen-1, self.datalen-1, self.datalen),
        1, self.data[-1])

    def test_range_single_bad(self):
        resp = Conn().get(self.url, req_hdrs = {"Range":
            "bytes=%d-%d"%(self.datalen, self.datalen)})
        status, hdrs, body = parse(resp)
        self.assertContains(status, "416 Requested Range Not Satisfiable")

    def test_range_reasonable(self):
        self.drive_range("10-20", "10-20/%d" % self.datalen,
            20-10+1, self.data[10:20+1])

    def test_range_start_given(self):
        self.drive_range("10-", "10-%d/%d" % (self.datalen-1, self.datalen),
            self.datalen-10, self.data[10:])

    def test_range_end_given(self):
        self.drive_range("-25",
            "%d-%d/%d"%(self.datalen-25, self.datalen-1, self.datalen),
            25, self.data[-25:])

    def test_range_beyond_end(self):
        # expecting same result as test_range_end_given
        self.drive_range("%d-%d"%(self.datalen-25, self.datalen*2),
            "%d-%d/%d"%(self.datalen-25, self.datalen-1, self.datalen),
            25, self.data[-25:])

    def test_range_end_given_oversize(self):
        # expecting full file
        self.drive_range("-%d"%(self.datalen*3),
            "0-%d/%d"%(self.datalen-1, self.datalen),
            self.datalen, self.data)

    def test_range_bad_start(self):
        resp = Conn().get(self.url, req_hdrs = {"Range": "bytes=%d-"%(
            self.datalen*2)})
        status, hdrs, body = parse(resp)
        self.assertContains(status, "416 Requested Range Not Satisfiable")

    def test_range_backwards(self):
        resp = Conn().get(self.url, req_hdrs = {"Range": "bytes=20-10"})
        status, hdrs, body = parse(resp)
        self.assertContains(status, "416 Requested Range Not Satisfiable")

def make_large_file(fn, boundary, data):
    big = 1<<33
    assert big == 8589934592L
    assert str(big) == "8589934592"

    f = open(fn, "w")
    pos = boundary - len(data)/2
    f.seek(pos)
    assert f.tell() == pos
    assert f.tell() < boundary
    f.write(data)
    filesize = f.tell()
    assert filesize == pos + len(data)
    assert filesize > boundary
    f.close()
    return (pos, filesize)

class TestLargeFile2G(TestHelper):
    BOUNDARY = 1<<31

    def setUp(self):
        self.datalen = 4096
        self.data = "".join(
            [chr(random.randint(0,255)) for _ in xrange(self.datalen)])
        self.url = "/big.jpeg"
        self.fn = WWWROOT + self.url
        self.filepos, self.filesize = make_large_file(
            self.fn, self.BOUNDARY, self.data)

    def tearDown(self):
        os.unlink(self.fn)

    def drive_start(self, ofs):
        req_start = self.BOUNDARY + ofs
        req_end = req_start + self.datalen/4 - 1
        range_in = "%d-%d"%(req_start, req_end)
        range_out = "%s/%d"%(range_in, self.filesize)

        data_start = req_start - self.filepos
        data_end = data_start + self.datalen/4

        self.drive_range(range_in, range_out, self.datalen/4,
            self.data[data_start:data_end])

    def test_largefile_head(self):
        resp = Conn().get(self.url, method="HEAD")
        status, hdrs, body = parse(resp)
        self.assertContains(status, "200 OK")
        self.assertEquals(hdrs["Accept-Ranges"], "bytes")
        self.assertEquals(hdrs["Content-Length"], str(self.filesize))
        self.assertEquals(hdrs["Content-Type"], "image/jpeg")

    def test_largefile__3(self): self.drive_start(-3)
    def test_largefile__2(self): self.drive_start(-2)
    def test_largefile__1(self): self.drive_start(-1)
    def test_largefile_0(self): self.drive_start(0)
    def test_largefile_1(self): self.drive_start(1)
    def test_largefile_2(self): self.drive_start(2)
    def test_largefile_3(self): self.drive_start(3)

class TestLargeFile4G(TestLargeFile2G):
    BOUNDARY = 1<<32

if __name__ == '__main__':
    setUpModule()
    unittest.main()

# vim:set ts=4 sw=4 et:
