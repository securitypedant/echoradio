log.file.path := "/app/data/streams/$stream_stub/stream.log"
log.stdout := true

def cleanup()
  log("Shutting down, flushing buffers...")
end

on_shutdown(cleanup)

radio_input_stream = input.http("$stream_input", user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36")
radio_input_stream = mksafe(radio_input_stream)

output.file(
    %mp3,
    {time.string("/app/data/streams/$stream_stub/source/%H.mp3")},
    radio_input_stream,
    reopen_when=({0m}),
    fallible=true,
)

def log_and_return(path) =
  log("Now streaming: " ^ path)
  single(path)
end

zero = log_and_return('/app/data/streams/bbcradio2/source/00.mp3')
one = log_and_return('/app/data/streams/bbcradio2/source/01.mp3')
two = log_and_return('/app/data/streams/bbcradio2/source/02.mp3')
three = log_and_return('/app/data/streams/bbcradio2/source/03.mp3')
four = log_and_return('/app/data/streams/bbcradio2/source/04.mp3')
five = log_and_return('/app/data/streams/bbcradio2/source/05.mp3')
six = log_and_return('/app/data/streams/bbcradio2/source/06.mp3')
seven = log_and_return('/app/data/streams/bbcradio2/source/07.mp3')
eight = log_and_return('/app/data/streams/bbcradio2/source/08.mp3')
nine = log_and_return('/app/data/streams/bbcradio2/source/09.mp3')
ten = log_and_return('/app/data/streams/bbcradio2/source/10.mp3')
eleven = log_and_return('/app/data/streams/bbcradio2/source/11.mp3')
twelve = log_and_return('/app/data/streams/bbcradio2/source/12.mp3')
thirteen = log_and_return('/app/data/streams/bbcradio2/source/13.mp3')
fourteen = log_and_return('/app/data/streams/bbcradio2/source/14.mp3')
fifteen = log_and_return('/app/data/streams/bbcradio2/source/15.mp3')
sixteen = log_and_return('/app/data/streams/bbcradio2/source/16.mp3')
seventeen = log_and_return('/app/data/streams/bbcradio2/source/17.mp3')
eighteen = log_and_return('/app/data/streams/bbcradio2/source/18.mp3')
nineteen = log_and_return('/app/data/streams/bbcradio2/source/19.mp3')
twenty = log_and_return('/app/data/streams/bbcradio2/source/20.mp3')
twentyone = log_and_return('/app/data/streams/bbcradio2/source/21.mp3')
twentytwo = log_and_return('/app/data/streams/bbcradio2/source/22.mp3')
twentythree = log_and_return('/app/data/streams/bbcradio2/source/23.mp3')

$stream_switch_block

output_icecast_stream = fallback(track_sensitive=false, [icecast_stream, radio_input_stream])

output.icecast(fallible=true,
  %mp3,
  host="$icecast_private_host",
  port=$icecast_private_port,
  password="$icecast_source_password",
  name="$stream_name",
  genre="Radio",
  description="$stream_description",
  mount="/$stream_mount", 
  output_icecast_stream
)