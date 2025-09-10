log.file.path := "/app/data/streams/$stream_stub/stream.log"
log.stdout := true

def cleanup()
  log("Shutting down, flushing buffers...")
end

on_shutdown(cleanup)

radio_input_stream = input.http("$stream_input", user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36")
radio_input_stream = mksafe(radio_input_stream)

backup_bird_song_loop = playlist(reload_mode="rounds", "/app/fallback_audio/birdsong/")

backup_voice_loop = playlist(reload_mode="rounds", "/app/fallback_audio/voices")

backup_silence = blank()

output.file(
    %mp3,
    {time.string("/app/data/streams/$stream_stub/source/%H.mp3")},
    radio_input_stream,
    reopen_when=({0m}),
    fallible=true,
)

zero = single(fallible=true, '/app/data/streams/$stream_stub/source/00.mp3')
one = single(fallible=true, '/app/data/streams/$stream_stub/source/01.mp3')
two = single(fallible=true, '/app/data/streams/$stream_stub/source/02.mp3')
three = single(fallible=true, '/app/data/streams/$stream_stub/source/03.mp3')
four = single(fallible=true, '/app/data/streams/$stream_stub/source/04.mp3')
five = single(fallible=true, '/app/data/streams/$stream_stub/source/05.mp3')
six = single(fallible=true, '/app/data/streams/$stream_stub/source/06.mp3')
seven = single(fallible=true, '/app/data/streams/$stream_stub/source/07.mp3')
eight = single(fallible=true, '/app/data/streams/$stream_stub/source/08.mp3')
nine = single(fallible=true, '/app/data/streams/$stream_stub/source/09.mp3')
ten = single(fallible=true, '/app/data/streams/$stream_stub/source/10.mp3')
eleven = single(fallible=true, '/app/data/streams/$stream_stub/source/11.mp3')
twelve = single(fallible=true, '/app/data/streams/$stream_stub/source/12.mp3')
thirteen = single(fallible=true, '/app/data/streams/$stream_stub/source/13.mp3')
fourteen = single(fallible=true, '/app/data/streams/$stream_stub/source/14.mp3')
fifteen = single(fallible=true, '/app/data/streams/$stream_stub/source/15.mp3')
sixteen = single(fallible=true, '/app/data/streams/$stream_stub/source/16.mp3')
seventeen = single(fallible=true, '/app/data/streams/$stream_stub/source/17.mp3')
eighteen = single(fallible=true, '/app/data/streams/$stream_stub/source/18.mp3')
nineteen = single(fallible=true, '/app/data/streams/$stream_stub/source/19.mp3')
twenty = single(fallible=true, '/app/data/streams/$stream_stub/source/20.mp3')
twentyone = single(fallible=true, '/app/data/streams/$stream_stub/source/21.mp3')
twentytwo = single(fallible=true, '/app/data/streams/$stream_stub/source/22.mp3')
twentythree = single(fallible=true, '/app/data/streams/$stream_stub/source/23.mp3')

$stream_switch_block

output_icecast_stream = fallback(track_sensitive=false, [icecast_stream, $backup_track])

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
