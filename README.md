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
