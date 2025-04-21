log.file.path := "/app/data/streams/$stream_stub/stream.log"
log.stdout := true

def cleanup()
  log("Shutting down, flushing buffers...")
end

on_shutdown(cleanup)

radio_input_stream = input.http("$stream_input")
radio_input_stream = mksafe(radio_input_stream)

output.file(
    %mp3,
    {time.string("/app/data/streams/$stream_stub/source/%H.mp3")},
    radio_input_stream,
    reopen_when=({0m}),
    fallible=true,
)

zero = single('/app/data/streams/$stream_stub/source/00.mp3')
one = single('/app/data/streams/$stream_stub/source/01.mp3')
two = single('/app/data/streams/$stream_stub/source/02.mp3')
three = single('/app/data/streams/$stream_stub/source/03.mp3')
four = single('/app/data/streams/$stream_stub/source/04.mp3')
five = single('/app/data/streams/$stream_stub/source/05.mp3')
six = single('/app/data/streams/$stream_stub/source/06.mp3')
seven = single('/app/data/streams/$stream_stub/source/07.mp3')
eight = single('/app/data/streams/$stream_stub/source/08.mp3')
nine = single('/app/data/streams/$stream_stub/source/09.mp3')
ten = single('/app/data/streams/$stream_stub/source/10.mp3')
eleven = single('/app/data/streams/$stream_stub/source/11.mp3')
twelve = single('/app/data/streams/$stream_stub/source/12.mp3')
thirteen = single('/app/data/streams/$stream_stub/source/13.mp3')
fourteen = single('/app/data/streams/$stream_stub/source/14.mp3')
fifteen = single('/app/data/streams/$stream_stub/source/15.mp3')
sixteen = single('/app/data/streams/$stream_stub/source/16.mp3')
seventeen = single('/app/data/streams/$stream_stub/source/17.mp3')
eighteen = single('/app/data/streams/$stream_stub/source/18.mp3')
nineteen = single('/app/data/streams/$stream_stub/source/19.mp3')
twenty = single('/app/data/streams/$stream_stub/source/20.mp3')
twentyone = single('/app/data/streams/$stream_stub/source/21.mp3')
twentytwo = single('/app/data/streams/$stream_stub/source/22.mp3')
twentythree = single('/app/data/streams/$stream_stub/source/23.mp3')

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