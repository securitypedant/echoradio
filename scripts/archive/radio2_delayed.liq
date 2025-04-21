# Input the live stream
radio2 = input.http("http://stream.live.vc.bbcmedia.co.uk/bbc_radio_two")

# Create a queue to buffer the stream
delayed_radio2 = queue(id="delay")

# Add the live stream to the queue
add_to_queue(delayed_radio2, radio2)

# Create a fallback to ensure smooth playback
radio2_with_delay = fallback([delayed_radio2])

# Delay playback for 8 hours (28800 seconds)
schedule.push(id="delay", time=28800.)

# Output to Icecast
output.icecast(
    %mp3,
    host="localhost",
    port=8000,
    password="hackme",
    mount="/radio2_8hr",
    radio2_with_delay
)
