# VC Prep — l'app che si aggiorna da sola

Un sito personale per prepararti ai colloqui nei fondi VC. Ogni mattina, verso le 6, GitHub scarica le notizie da TechCrunch, Sifted, MIT Technology Review, Tech.eu, EU-Startups, Crunchbase News e StartupItalia. Seleziona quelle utili, riconosce round e importi, segue 360 Capital e le sue partecipate e aggiorna il sito. Tu lo apri dal telefono o dal computer. Non serve Claude, non serve tenere acceso il computer e non costa nulla.

**Cosa trovi nel sito:** Oggi (le 5 notizie da leggere, la domanda del giorno, i round più grandi, le notizie sui fondi che segui) · Notizie · Round e fondi · Il colloquio · Banca opinioni · Fondi · Allenamento sui pitch deck.

---

## Messa in funzione (circa 15 minuti, una volta sola)

Serve solo il browser.

### 1. Crea un account GitHub
Vai su [github.com/signup](https://github.com/signup) e registrati: è gratuito. Scegli bene il nome utente, perché comparirà nell'indirizzo del sito.

### 2. Crea il repository
1. In alto a destra clicca **+** → **New repository**.
2. **Repository name:** `vc-prep`
3. Seleziona **Public**: è necessario per avere il sito gratis. Il sito non contiene dati riservati, vedi più sotto.
4. Non spuntare nient'altro e clicca **Create repository**.

### 3. Carica i file
1. Nella pagina del repository vuoto clicca il link **uploading an existing file**.
2. Apri la cartella `vc-prep-web` sul tuo computer e trascina nella pagina **il suo contenuto, non la cartella stessa**: le cartelle `config`, `data`, `scripts`, `template` e i file `README.md` e `workflow-da-copiare.yml`.
3. Aspetta che finisca il caricamento e clicca **Commit changes**.

> Se trascini la cartella intera, i file finiscono in una sottocartella e l'aggiornamento automatico non li trova.

### 4. Crea l'aggiornamento automatico
1. Nel repository clicca **Add file** → **Create new file**.
2. Come nome del file scrivi esattamente `.github/workflows/aggiorna.yml`. Mentre scrivi le barre `/`, GitHub crea le cartelle da solo.
3. Sul tuo computer apri `workflow-da-copiare.yml` con TextEdit (o Blocco note), seleziona tutto, copia e incolla nella pagina di GitHub.
4. Clicca **Commit changes** e poi di nuovo **Commit changes**.

### 5. Attiva il sito
**Settings** (in alto nel repository) → **Pages** (menu a sinistra) → alla voce **Source** scegli **GitHub Actions**.

### 6. Lancia il primo aggiornamento
1. Apri la scheda **Actions**. Se compare un avviso sui workflow, clicca il pulsante verde per abilitarli.
2. A sinistra clicca **Aggiorna VC Prep** → **Run workflow** → **Run workflow**.
3. Dopo 1-2 minuti il pallino diventa verde ✓.

### 7. Apri il sito
L'indirizzo è `https://TUO-NOME-UTENTE.github.io/vc-prep/` e lo trovi anche in **Settings → Pages**.

- **iPhone:** apri il sito in Safari → Condividi → **Aggiungi alla schermata Home**.
- **Android:** Chrome → menu ⋮ → **Aggiungi a schermata Home**.

Da qui in poi si aggiorna da solo ogni mattina.

---

## Se qualcosa non va

| Problema | Soluzione |
|---|---|
| Il workflow fallisce al passo «Salva l'archivio» con un errore 403 o di permessi | Settings → Actions → General → **Workflow permissions** → **Read and write permissions** → Save. Poi rilancia (punto 6). |
| Il workflow fallisce al passo «deploy» | Controlla il punto 5: la Source di Pages deve essere **GitHub Actions**. |
| Il sito dice che l'aggiornamento è fermo | Apri Actions e guarda l'ultima esecuzione. Se il workflow risulta disattivato, aprilo e clicca **Enable workflow**. GitHub disattiva i workflow programmati dopo 60 giorni senza attività, ma qui il salvataggio quotidiano dell'archivio dovrebbe evitarlo. |
| Una fonte risulta «non raggiungibile» nella sezione Oggi | Capita: il sito usa le altre fonti e ci riprova il giorno dopo. |

---

## Privacy

- Il sito è pubblico ma non indicizzato dai motori di ricerca: lo vede solo chi ha il link.
- **Non contiene i dati riservati delle slide del corso.** Numeri interni delle partecipate e dettagli personali sono stati tolti. La versione completa resta nel progetto privato `vc-interview-prep` sul tuo Mac.
- Le tue note (posizioni, checklist, storico degli allenamenti, notizie lette o salvate) restano **nel browser del dispositivo** che usi e non finiscono su GitHub. Per passarle da un dispositivo all'altro usa **Esporta le mie note** e **Importa**, in fondo alla pagina.

---

## Personalizzare (senza programmare)

Tutto si modifica dal sito di GitHub: apri il file, clicca la matita ✏️, modifica e fai **Commit changes**. Il cambiamento compare al prossimo aggiornamento, oppure subito se rilanci il workflow (punto 6).

- **Seguire un altro fondo:** in `config/funds.json` aggiungi un blocco con la stessa struttura di 360 Capital. Il modo più comodo è chiedere a Claude, in una chat, di prepararlo nello stesso formato e poi incollarlo. Il campo `watch` contiene i nomi da cercare nelle notizie (il fondo e le sue partecipate).
- **Affinare un tema:** in `config/topics.json` ogni tema ha le sue `keywords`. Una parola con `*` finale vale come prefisso (per esempio `robot*` trova anche robotics).
- **Aggiungere una fonte:** in `config/sources.json` aggiungi un feed RSS. Con `mode: all` tiene tutto, con `signals` solo le notizie con round, fondi, exit o temi.
- **Cambiare orario:** in `.github/workflows/aggiorna.yml` modifica la riga `cron` (l'orario è UTC).

## Come sceglie le notizie

Niente AI, solo regole trasparenti in `scripts/update.py`:
- scarta promozioni di eventi, contenuti sponsorizzati e notizie fuori tema;
- riconosce round (importo, stadio, azienda), nuovi fondi ed exit dai titoli;
- collega ogni notizia ai temi della Banca opinioni tramite le parole chiave;
- assegna un punteggio: più alto per round, fondi ed exit, Italia ed Europa, fondi che segui e fonti consigliate a lezione;
- tiene in archivio le notizie degli ultimi 45 giorni.
