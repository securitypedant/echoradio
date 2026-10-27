# Programme-guide feeds by station (research, verified 2026-10-27)

All endpoints below were fetched successfully from the US (California) on 2026-10-27 unless marked
UNVERIFIED. Most are undocumented app/web APIs without a stated licence; treat them as best effort.
"Geo" is whether the *stream* played from the US. RadioDNS/SPI is an open broadcast standard.

Already implemented in EchoRadio: **BBC** (`rms.api.bbc.co.uk/v2/broadcasts/schedules/<service>/<date>`),
**KEXP** (`api.kexp.org/v2/shows`, `/v2/plays`), **manual weekly schedule**.

## Tier 1 — full dated day grids, public JSON/XML, no key (implementable as generic providers)

| Provider | Covers | Endpoint pattern | Fields | Horizon | Notes |
|---|---|---|---|---|---|
| **Bauer UK** (`listenapi.planetradio.co.uk/api9.2`) | Absolute (`abr`), Magic (`mag`), KISS (`ki1`), Greatest Hits (`gh0`), Absolute 80s (`ab8`), Magic Soul (`mso`), Mellow Magic (`mel`) … 41 UK stations (`/api9.2/stations/UK`) | `/schedule/{code}/{YYYY-MM-DDTHH:MM:SS}/{end}` → `{date:[{title, shortdesc, start, duration, image_url}]}`; now-playing `/nowplaying/{code}`; history `/events/{code}/{date}/{limit}` | title (presenter in title), synopsis, start, duration, image, track now-playing | months both ways | Direct MP3/AAC streams return 500 from the US; HLS `hls-*.hellorayo.co.uk/...playlist.m3u8` works. |
| **RadioDNS SPI EPG** (XML, one parser) | Global: Classic FM, LBC, Heart, Capital (`epg.musicradio.com`, HTTP); News UK: Virgin Radio, Times Radio (`wireless.radiodns.metadata.radio`); Deutschlandfunk, Dlf Kultur (`rdns.deutschlandradio.de`); ARD: WDR 2, Bayern 3, radioeins (`de<ard>.radiodns.ard.de`, "POC" server); NDR publishes SI but no PI | `http(s)://<host>/radiodns/spi/3.1/dab/<gcc>/<eid>/<sid>/<scids>/<YYYYMMDD>_PI.xml` (follow 301s). Bearer IDs from `https://radiodns.uk/services.json` or the host's `SI.xml`. Host via DNS SRV `_radioepg._tcp.<fqdn>` / `_radiospi._tcp` | short/medium/longName, time + duration, descriptions, images, credits (varies by broadcaster) | Global: template-like (same shows any date); News UK ≈ 1 week; Dlf −7…+4 d; ARD +3…+6 d | Examples: Classic FM `dab/ce1/c181/c2a1/0`, LBC `dab/ce1/c181/c0c2/0`, Heart UK `dab/ce1/c181/cfd1/0`, Capital UK `dab/ce1/c181/c5da/0`, Virgin `dab/ce1/c19a/c3d8/0`, Times `dab/ce1/c19a/c0d8/0`, Dlf `dab/de0/10bc/d210/0`, Dlf Kultur `dab/de0/10bc/d220/0`, WDR 2 `dab/de0/10fa/d992/0`, Bayern 3 `dab/de0/10a5/d313/0`, radioeins `dab/de0/1019/d332/0`. Virgin's stream is geo-blocked outside the UK. |
| **ORF** (Austria) | Ö1, Ö3, FM4 (`audioapi.orf.at/{oe1|oe3|fm4}/api/json/4.0/…`) | `/broadcasts/{YYYYMMDD}`, `/broadcast/{programKey}/{YYYYMMDD}` (detail: description, moderator, images, song `items[]`), `/live` | title, subtitle, programme, scheduled/actual start+end, presenter, synopsis, images, songs | −30 d … +5 wk | Richest feed found. |
| **ABC** (Australia) | RN (`RN`), triple j (`triplej`), ABC Sydney (`local_sydney`), ~100 services (`/api/v1/services.json`) | `https://program.abcradio.net.au/api/v1/programitems/search.json?service={id}&from={ISO}&to={ISO}&limit=50` | title, synopses, presenters, start/end (UTC), programme, URL; no image | ~6 d ahead, years back | triple j songs: `https://music.abcradio.net.au/api/v1/plays/search.json?station=triplej`. Use HLS or `abc.streamguys1.com` streams from abroad. |
| **RTÉ** (Ireland) | Radio 1, 2FM, lyric fm, RnaG | `https://www.rte.ie/radio/{radio1|2fm|lyricfm|rnag}/schedule/{YYYYMMDD}/` (returns JSON) | showName, showTime (local HH:MM), showEndDate, image, URL | ~2 wk ahead, ~4 wk back | Songs: `https://onair.radioapi.io/rte/{rteradio1|rte2fm}/onair.json` (unofficial). |
| **Sveriges Radio** | P1 (132), P2 (163), P3 (164), P4 Stockholm (701), … | `https://api.sr.se/api/v2/scheduledepisodes?channelid={id}&date=YYYY-MM-DD&format=json&pagination=false` | title, subtitle, description, UTC start/end, programme, images | ≥1 yr back, ~3.5 wk ahead | Songs: `/api/v2/playlists/rightnow?channelid=`. Documented, "no longer maintained but usable". |
| **NRK** (Norway) | P1, P2, P3, … | `https://psapi.nrk.no/epg/{slug}?date=YYYY-MM-DD` | title, seriesTitle, description, plannedStart/actualStart, ISO duration, images | −8 wk … +19 d | Documented at psapi.nrk.no/documentation. |
| **Rai** (Italy) | Radio 1/2/3 (`rai-radio-N`) | `https://www.raiplaysound.it/palinsesto/app/{slug}/{DD-MM-YYYY}.json`; now/next all channels `/palinsesto/onAir.json` | title, episode_title, description, UTC start/end, images, programme | −8 … +6 d | |
| **RTP** (Portugal) | Antena 1 (1), Antena 2 (2), Antena 3 (3), … | `https://www.rtp.pt/EPG/json/rtp-channels-page/list-grid/radio/{code}/{YYYY-MM-DD}` | name, series, description (presenter), episode, images; start only (end = next start) | −2 mo … +3 d | Now-playing: `https://www.rtp.pt/play/livechannelonairnow.php?channel=at1|at3`. |
| **WNYC / WQXR** (New York) | `wnyc-fm939`, `wqxr`, `q2` | `https://wnyc.org/api/schedule/{slug}?filterMode=specificDate&startDate=YYYY-MM-DD` | start/end (UTC), show title, synopsis, image, presenter ids | ~7 d ahead | Now/next: `https://api.wnyc.org/api/v1/whats_on/{slug}/`. |
| **NPR Composer** (US member stations) | Any station using Composer (needs its 24-hex UCS id, found per station) | `https://api.composer.nprstations.org/v1/widget/{UCS}/day?format=json&date=YYYY-MM-DD`, `/now`, `/week` | start/end (UTC + local), title, synopsis, hosts, link | weeks both ways | UCS for KQED/WBEZ not found; WLRN verified. |

## Tier 2 — today-only grids or now/next only (usable for a rolling guide, not for rewinding days)

| Provider | Covers | Endpoint | Limitation |
|---|---|---|---|
| **CBC** (Canada) | Radio One, CBC Music (`program-queue/{1|2}/{location}`), now/next via `cbc.ca/graphql linearScheduleOnNow(callSign:)` | `https://www.cbc.ca/listen/api/v1/program-queue/{network}/{location}` | today only; host + image |
| **Ici Radio-Canada** | Première, ICI Musique | `POST https://services.radio-canada.ca/bff/audio/graphql` `broadcastSchedule(params:{regionId,broadcastingNetworkId,device:"Web",liveSchedule:true})` | hosts, pictures, track lists; `date` input UNVERIFIED |
| **RTVE / RNE** (Spain) | R1, R2, R3, R5, R6 | `https://api.rtve.es/servicios/programasRadio/{R1..R6}.json` | today only; presenter, images |
| **NPO** (Netherlands) | Radio 1, Radio 2, 3FM | `https://www.nporadio{1|2}.nl/api/broadcasts`, `https://www.npo3fm.nl/api/broadcasts`; songs `/api/tracks` | today only; local times without offset |
| **2GB** (Sydney) | 2GB | `https://www.2gb.com/wp-json/json/schedule` | current week only |
| **RNZ** (New Zealand) | National, Concert | `https://www.rnz.co.nz/{national|concert}/schedules/{YYYYMMDD}.xml` | ~3 d ahead; no end times; **CC BY-ND licence** (credit "Radio New Zealand Limited") |
| **Radio France** | France Inter (1), franceinfo (2), France Musique (4), France Culture (5), Mouv' (6), FIP (7) | `https://api.radiofrance.fr/livemeta/live/{id}/{inter_player|info_player|culture_player|musique_player|mouv_player|fip_player}`; FIP songs `fip_extended`; last 12 h `livemeta/pull/{id}` | prev/now/next only; full grid needs free token (ToS discourages stream aggregators) |
| **RTBF** (Belgium) | La Première, Classic 21, … | `https://bff-service.rtbf.be/auvio/v1.23/widgets/18858` (current programme, all channels); songs `https://api.streamabc.net/metadata/channel/{streamId}.json` | now only |
| **SRG SSR** (Switzerland) | SRF 1/3/Virus, RTS Première | `https://il.srgssr.ch/integrationlayer/2.0/channel/byUrn/{urn}/nowAndNext`; songs `/2.0/{srf|rts}/songList/radio/byChannel/{id}` | now/next; day EPG needs API key |
| **DR** (Denmark) | P1, P3, P4 | `https://api.dr.dk/radio/v5/schedules/all/now`, `/v5/channels` | now only; day schedules need `x-apikey` |
| **iHeart** (US) | Z100 etc. | song history `https://api.iheart.com/api/v3/live-meta/stream/{id}/trackHistory`; schedule only as HTML on station sites | songs only |
| **KCRW** | | `https://tracklist-api.kcrw.com/Simulcast` (songs with programme block fields) | site bot-walled |

## Nothing usable (HTML only, bot-blocked, or credentials required)

NPR national, KQED, CJAD, CHFI, Newstalk (IE), Today FM, Newstalk ZB, The Edge, Nova/Smooth (429),
VRT (login), Yle (key), Cadena SER / Los 40 (JWT), COPE, RTL.fr, NRJ, Europe 1 (bot-blocked),
RTL 102.5, Radio Deejay, Rádio Comercial, NDR 2 (now-playing only), Bayern 3 now-playing.

## Streams geo-blocked from the US

Virgin Radio UK (barker MP3), Bauer UK direct Icecast (500; HLS fine), ABC `mediahubaustralia` MP3
(403; HLS/streamguys fine). Everything else listed played from the US.
