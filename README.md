### Why?

Networked music performance is hard, because [30 ms of latency](https://dl.acm.org/doi/10.1145/1167838.1167862) is about as much as humans can tolerate before delay becomes noticeable. But we have [Opus](http://opus-codec.org/) now, which encodes and decodes quite well at frame sizes of 2.5 and 5 ms. And video-enabled remote work and Netflix have surely made the pipes wider.

Does this already exist? Possibly, but let's give it another try, anyway.

### Setup

On OS X, use [Homebrew](https://brew.sh) to install Opus and PortAudio:

```
$ brew install opus portaudio
```

Create and activate a Python3 virtualenv:

```
$ python3 -m venv /some/directory
$ source /some/directory/bin/activate
```

Then install the Python packages:

```
$ pip install -r requirements.txt
```

It's best to run the client with stderr redirected to a file:

```
$ python3 client.py 2> output.log
```
