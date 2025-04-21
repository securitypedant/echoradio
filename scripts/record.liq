log.file.path := "record.log"
log.stdout := true

radio = input.http("http://lstn.lv/bbcradio.m3u8?station=bbc_radio_two&bitrate=96000")
radio = mksafe(radio)

output.file(
    %mp3,
    {time.string("archive/%H.mp3")},
    radio,
    reopen_when=({0m}),
    fallible=true,
)