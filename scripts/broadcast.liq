log.file.path := "casting.log"
log.stdout := true

zero = single('archive/00.mp3')
one = single('archive/01.mp3')
two = single('archive/02.mp3')
three = single('archive/03.mp3')
four = single('archive/04.mp3')
five = single('archive/05.mp3')
six = single('archive/06.mp3')
seven = single('archive/07.mp3')
eight = single('archive/08.mp3')
nine = single('archive/09.mp3')
ten = single('archive/10.mp3')
eleven = single('archive/11.mp3')
twelve = single('archive/12.mp3')
thirteen = single('archive/13.mp3')
fourteen = single('archive/14.mp3')
fifteen = single('archive/15.mp3')
sixteen = single('archive/16.mp3')
seventeen = single('archive/17.mp3')
eighteen = single('archive/18.mp3')
nineteen = single('archive/19.mp3')
twenty = single('archive/20.mp3')
twentyone = single('archive/21.mp3')
twentytwo = single('archive/22.mp3')
twentythree = single('archive/23.mp3')

radio = input.http("http://lstn.lv/bbcradio.m3u8?station=bbc_radio_two&bitrate=96000")
radio = mksafe(radio)

stream = switch(track_sensitive=false,[
   ({0h}, sixteen),
   ({1h}, seventeen),
   ({2h}, eighteen),
   ({3h}, nineteen),
   ({4h}, twenty),
   ({5h}, twentyone),
   ({6h}, twentytwo),
   ({7h}, twentythree),
   ({8h}, zero),
   ({9h}, one),
   ({10h}, two),
   ({11h}, three),
   ({12h}, four),
   ({13h}, five),
   ({14h}, six),
   ({15h}, seven),
   ({16h}, eight),
   ({17h}, nine),
   ({18h}, ten),
   ({19h}, eleven),
   ({20h}, twelve),
   ({21h}, thirteen),
   ({22h}, fourteen),
   ({23h}, fifteen)
])

final_stream = fallback(track_sensitive=false, [stream, radio])

output.icecast(fallible=true,
  %mp3,
  host="localhost",
  port=8000,
  password="pl4yinGtune5",
  name="BBC Radio 2",
  genre="Radio",
  description="BBC Radio 2 - delayed by 8 hours",
  mount="/radio2_8hr",
  final_stream
)