
# EchoRadio

## Listen to international radio in your local timezone

Wish you could wake up to your favorite New York radio station breakfast show and go to sleeping listening to Australian talk radio? I created this app to help you do just that. Add internet streams, chosing the timezone they are broadcast in and the timezone you want to listen in. EchoRadio will record the stream, and then rebroadcast matching the content to your local time.

![EchoRadio screenshot](echoradio-screenshot.png)

## 🚀 Features

- Dockerized for deployment with Docker Compose or Swarm
- Web interface to manage and play audio streams
- Secure admin authentication (optional)
- Supports multiple streams

## ⚙️ Setup

You can either build from source, or it's much easier to deploy the existing Docker Hub image.

1. Deploy using image from [Docker Hub](https://hub.docker.com/repository/docker/simonsecuritypedant/echoradio/general)
2. By default, access the web interface at http://host:8080, and the Icecast instance at http://host:8000. These can be fine if you are just listening on your local network. However, if you want to stream over the Internet. Highly recommend using Cloudflare tunnels to expose services. (I will create an instruction video soon)
3. When accessing for the first time, set passwords for Icecast admin and streaming. Also, set Icecast hostname, protocol and port for what is the Internet accessible address. These values will be used in the web interface. You can also set an admin password so that you can share the URL with others to listen.
4. Add streams, by default you can add 3. But use settings to increase as you need.

## 🔥 Upcoming changes

### Next release

- Fix issue so that when it's recorded the full delay, does it switch from live stream to recorded content?

### Backlog and feature requests

- Add stream URL test prior to adding.
- Expose log retention in settings
- Consider moving add new stream into a seperate page
- Add ability to know if the stream is currently synced or catching up. Highlight which mp3 is currently being written.
- Build an API to allow search for radio streams.
- Look at adding metadata in the rebroadcast stream. Copy anything that might be in the source.
- Create an echoradio log, showing adding, deleting, starting, stopping streams etc
- When the container is restarted, check status of streams and update their metadata

## 📝 License

MIT License

## ✨ Credits

Built by [Simon Thorpe](https://github.com/simonthorpe)  
Inspired by the power of community broadcasting.

## Building docker image

### Local

- docker build --build-arg FLASK_ENV=development . -t echoradio

### Docker hub

docker buildx build \
  --platform linux/amd64,linux/arm64 \
  -t simonsecuritypedant/echoradio:latest \
  --push .