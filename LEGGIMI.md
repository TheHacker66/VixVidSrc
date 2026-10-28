# VidSrc + VixSrc — 0.4.1

## Correzione sottotitoli VixSrc

Le tracce WebVTT indicate nelle playlist HLS vengono ora recuperate e collegate
esplicitamente a Kodi come file .vtt. Non vengono convertite in SRT.
La versione precedente saltava questo caricamento quando rilevava tracce HLS,
affidandosi alla loro esposizione automatica nel lettore.

Installa lo ZIP sopra la 0.4.0. In Impostazioni seleziona Sottotitoli esterni →
Automatici oppure Scegli prima di riprodurre. Poi riavvia il titolo e apri il
menu Sottotitoli/CC di Kodi per attivare o selezionare la traccia.
La selezione Disattivati evita anche il nuovo download esplicito.

Automatici recupera fino a una traccia completa e una forced per ciascuna lingua
preferita, se disponibili. Le tracce complete hanno precedenza; una forced
contiene solo alcuni dialoghi o scritte e non equivale a una traccia completa.
Le varianti complete CC sono usate se manca una variante completa standard.
I file forced hanno il suffisso .forced.vtt per distinguerli nel lettore.

Quando una traccia contiene un solo segmento WebVTT, il contenuto viene
conservato. Le tracce suddivise vengono unite in WebVTT preservando formattazione,
impostazioni delle battute e timestamp, con gestione delle mappe MPEGTS e delle
discontinuità. Il download è limitato a 64 segmenti e 16 MiB per traccia, con
un budget di 30 secondi controllato tra le richieste; ciascuna richiesta ha
timeout di 8 secondi. Tracce cifrate o byte-range non sono supportate da questo
caricamento esplicito. Gli errori non impediscono l’avvio del video.

Validazione: 37 test locali, inclusi rilevamento delle tracce nel resolver,
salvataggio .vtt, lingue, complete/forced, cache, segmenti multipli, formattazione,
mappe timestamp e limiti di download. Prova live riuscita: scaricate e salvate
due tracce WebVTT (italiano forced e inglese completo) da un master VixSrc reale.
La visualizzazione sul Vero resta da provare.

## Nuova fonte VixSrc

VixSrc si aggiunge a VidSrc. Il catalogo TMDb, le ricerche salvate e i preferiti
sono comuni alle due fonti. Installa lo ZIP sopra la versione precedente:
l’ID addon e il database locale rimangono gli stessi.

Al primo utilizzo la voce Fonte video è Scegli ogni volta: prima di riprodurre
puoi scegliere VixSrc oppure VidSrc. Nelle impostazioni puoi fissare una delle
due come predefinita. Sulla voce Riproduci di un film o su un episodio trovi
anche il menu contestuale Riproduci con VixSrc / Riproduci con VidSrc, che
sovrascrive la preferenza per quella riproduzione. I vecchi collegamenti play
senza parametro source rispettano la nuova impostazione.

VixSrc segue il percorso API movie/tv → src del player → masterPlaylist → HLS.
Il token e la scadenza vengono letti a ogni avvio dalla pagina corrente.
La configurazione viene letta come soli dati letterali, senza eseguire script
remoti. Non servono Node.js né WASM per VixSrc; rimangono necessari per VidSrc.
In caso di errore della playlist il resolver prova i server alternativi della
stessa pagina. Non cambia automaticamente fonte dopo l’avvio del video.

Il resolver richiede lang=it e conserva tutte le tracce della playlist.
Nelle prove live il master indica italiano come audio predefinito, ma la
selezione finale dipende dalle impostazioni di Kodi e dalla disponibilità del
titolo. Durante la riproduzione puoi scegliere Italiano dal menu Audio.
I sottotitoli HLS vengono anche scaricati come WebVTT nelle lingue configurate
e passati esplicitamente al lettore. Quando il download riesce, Automatici non
effettua ricerche esterne aggiuntive per quella lingua. Scegli prima di
riprodurre continua a permettere la ricerca esterna. Se mancano tracce HLS o
il loro download fallisce, rimane disponibile il recupero esterno precedente.

La presenza nel catalogo TMDb non garantisce che il titolo sia disponibile su
entrambe le fonti, né garantisce una specifica lingua. Per problemi su una fonte
puoi selezionare l’altra, senza cambiare catalogo o preferiti.

Validazione 0.4.0: 30 test locali su entrambe le fonti, parser dei dati VixSrc,
URL firmati e parametri lingua, server alternativi, sottotitoli HLS e comandi
di riproduzione per fonte. Prove live del nuovo resolver per un film e un
 episodio tramite ID IMDb: API, player e playlist HLS ottenuti con successo.
Verificati anche esempi con ID TMDb. Non è stata verificata la riproduzione
 effettiva del nuovo provider su Kodi/Vero o Windows in questo ambiente.

Documentazione pubblica della fonte: https://vixsrc.to/ .

## Diagnostica WASM su Vero / Windows

La versione 0.3.1 usa require('fs') e un fallback util.TextDecoder per ridurre
le dipendenze dalle forme più recenti delle API Node. Non è una correzione
confermata del problema segnalato sul Vero: manca ancora il dettaglio del guasto.

Nel menu principale seleziona Test Node/WASM. Il test verifica localmente
compilazione, istanziazione, memoria, interfaccia alloc/decrypt e decodifica UTF-8
con un modulo sintetico; non effettua richieste di rete o usa token. Mostra
versione e architettura di Node. Non dimostra che il modulo remoto sia compatibile.

Se il test passa, riprova un film. Gli errori WASM ora indicano phase, category,
error, node, arch, platform ed exit, senza il contenuto dei token o stderr grezzo.
Invia il messaggio completo per distinguere runtime, compilazione, istanziazione,
memoria, decifratura e decodifica. Una risposta del server senza la firma WASM
viene segnalata prima dell’esecuzione. Il timeout del helper è 20 secondi.
Un exit negativo su Linux può indicare un segnale: il codice viene riportato
ma non viene attribuita automaticamente una causa.

## Sottotitoli

La versione 0.3.0 recupera le tracce default_subs restituite dal servizio e cerca
sullo stesso endpoint OpenSubtitles usato dal subtitles.js osservato su VidSrc.
Non richiede credenziali OpenSubtitles aggiuntive. Disponibilità e accesso
all’endpoint dipendono dal servizio e dalla rete.

Nelle impostazioni:
- Automatici: prova italiano e inglese, preferendo le
  tracce incluse nel video e poi le versioni OpenSubtitles con maggiore affinità
  al nome del file video; se un download fallisce prova altre versioni.
  Per VixSrc recupera anche le varianti complete e forced disponibili via HLS.
- Scegli prima di riprodurre: mostra le tracce del servizio e i risultati nelle
  lingue configurate, con il nome della versione. Annulla avvia senza tracce
  esterne. Puoi scegliere una versione diversa se la sincronizzazione non va.
- Disattivati: nessuna ricerca o download di sottotitoli esterni.

Lingue: elenco fino a tre codici, ad esempio it,en,fr (anche ita,eng,fre).
I file sono aggiunti al lettore Kodi: durante il video apri Sottotitoli/CC per
attivarli o scegliere la traccia. Visibilità iniziale, stile e ritardo sono
controllati dalle impostazioni native di Kodi. Le tracce HLS eventualmente già
presenti rimangono gestite dal lettore.

SRT, VTT e ASS vengono scaricati e mantenuti nel profilo addon/subtitles.
Supportati gzip, ZIP senza estrazione su disco e conversione codifica in UTF-8.
Cache locale riutilizzabile per sette giorni: i file più vecchi non sono eliminati
automaticamente. Le URL firmate non sono salvate nei nomi file. Gli errori dei
sottotitoli non impediscono la riproduzione. La ricerca può aggiungere alcuni
secondi all’avvio; puoi disattivarla nelle impostazioni.

Prova live: lo script VidSrc è stato recuperato e ispezionato. La richiesta
OpenSubtitles dall’ambiente di sviluppo ha risposto HTTP 403 anche con gli
header del player; il recupero live dal dispositivo dell’utente resta da provare.
La sincronizzazione perfetta non può essere garantita dal solo nome release.

## Catalogo

- Cataloghi film: popolari, più votati, al cinema, in arrivo.
- Cataloghi serie TV: popolari, più votate, in onda.
- Ricerca film, serie oppure entrambe; locandine, sfondi, anno e trama.
- Pagine successive per cataloghi e risultati di ricerca.
- Serie → stagioni → episodi → riproduzione, senza inserire ID.
- Preferiti locali per film e serie, con aggiunta/rimozione dalla scheda titolo
  oppure dal menu contestuale (tasto destro o menu del telecomando).
- Ricerche recenti salvate automaticamente, fino a 100; seleziona una voce
  per ripeterla. Il menu contestuale elimina una ricerca, mentre Svuota
  cronologia ricerche elimina tutte le voci dopo conferma.

## Aggiornamento dalle versioni precedenti

Installa questo ZIP sopra la versione precedente da Kodi → Add-on → Installa
 da un file ZIP. Mantiene lo stesso ID addon: non occorre disinstallare.
Le impostazioni del resolver e il percorso Node.js vengono mantenuti da Kodi.
Il resolver conserva il risultato precedente e rende disponibili anche i metadati
per i sottotitoli. I file esterni vengono collegati al ListItem prima dell’avvio.

## Configurazione TMDb (necessaria per il catalogo)

1. Accedi al tuo account su https://www.themoviedb.org/ e apri
   https://www.themoviedb.org/settings/api .
2. Ottieni una credenziale API personale seguendo le indicazioni di TMDb.
3. Nelle impostazioni dell’addon inserisci il valore completo in
   TMDb API Read Access Token; non aggiungere il prefisso Bearer.
   In alternativa compila TMDb API Key v3. Basta uno dei due campi.
   Il token, quando presente, ha la precedenza sulla API Key.
4. La lingua predefinita è it-IT; puoi modificarla nelle impostazioni.

Non serve autenticare l’addon al tuo account TMDb per salvare i preferiti:
preferiti e ricerche sono locali, non sincronizzati con TMDb né tra dispositivi.
Le credenziali rimangono nelle impostazioni Kodi; non sono incluse negli URL
interni del plugin o nei log. Non condividere il file delle impostazioni.

## Utilizzo

Apri Film o Serie TV dal menu, oppure Cerca film e serie TV. Seleziona un film
per la sua scheda e poi Riproduci; per una serie seleziona stagione ed episodio.
Le copertine e gli sfondi sono esposti alla skin Kodi: per una griglia visuale
seleziona una vista a poster nelle opzioni della skin. Nessuna vista specifica
viene imposta a skin diverse.

I preferiti sono film o serie intere, non singoli episodi. Il catalogo delle
stagioni omette la stagione zero (speciali), perché il resolver attuale richiede
stagioni positive. Il catalogo può includere titoli o episodi futuri e non
verifica preventivamente la disponibilità video.

## Dati locali

Preferiti e ricerche sono nel file catalogo.sqlite del profilo dell’addon.
Persistono dopo riavvii e aggiornamenti. La disinstallazione con rimozione dei
dati o la cancellazione del profilo li elimina. Nessun token video viene
salvato in questo database. La cronologia viene deduplicata per tipo e testo,
ignorando maiuscole e spazi ripetuti; una ricerca ripetuta torna in cima.

## Requisiti della riproduzione

Kodi con Python 3 (19 o successivo). Per la fonte VidSrc serve anche Node.js
esterno con supporto WebAssembly; VixSrc non usa Node.
Usa una versione Node LTS supportata adatta al sistema e all’architettura.
Su Windows indica il percorso completo di node.exe; su Debian verifica con
command -v node. Non servono npm, pacchetti JS o un server in ascolto.
Resta disponibile l’inserimento manuale degli ID nel menu principale.

Il resolver VidSrc segue vs_src.php → eventuale landing CFG.playerUrl → CONFIG →
API con token monouso → WASM → generate.php → playlist HLS. Il WASM gira in
un processo Node separato, senza import di sistema, con timeout. Il limite
heap V8 non è un limite totale della memoria del processo/WASM.
I controlli browser eventualmente richiesti dal servizio non vengono aggirati.

## Diagnostica

Per errori CONFIG, abilita Salva risposta HTML su errore CONFIG, riprova e usa
Esporta diagnostica. La rimozione automatica dei token noti è parziale:
controlla sempre il file prima di condividerlo. Poi disattiva la diagnostica.
Ogni nuova riproduzione elimina la risposta diagnostica precedente.

## Validazione

37 test locali: percorso del resolver, interfaccia WASM con modulo sintetico,
landing e rinnovo token, credenziali TMDb, Unicode nelle ricerche, persistenza,
deduplicazione e limite cronologia, preferiti, paginazione e filtraggio dei
risultati, navigazione serie → episodio e passaggio dell’ID IMDb al resolver.
Aggiunti test su lingue, formati e codifiche, gzip/ZIP, dimensioni decompresse,
ordinamento delle versioni, URL di ricerca per episodio, tracce API, cache e
fallback in caso di errore del provider.
Aggiunti self-test Node reale e test di errore compilazione con diagnostica.
Verificati inoltre sintassi Python, XML e integrità ZIP.
Le chiamate TMDb e l’interfaccia Kodi sono simulate nei test: nessuna verifica
live del nuovo catalogo con una credenziale personale o su Vero/Windows.
L’utente ha confermato funzionante la riproduzione della versione 0.1.3.

## Attribuzione

Metadati e immagini: The Movie Database, https://www.themoviedb.org/ .
This product uses the TMDB API but is not endorsed or certified by TMDB.
La presenza su TMDb non garantisce la disponibilità sul servizio video.
Usare contenuti per cui si dispone dell’autorizzazione alla visione.
