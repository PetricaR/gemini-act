# De la „chatbot care răspunde” la „agent care face treaba”: Gemini Act

Majoritatea asistenților AI din companii fac un singur lucru bine: îți răspund la întrebări. Citesc niște documente, generează un text, sumarizează un mail — dar la finalul conversației, tot tu deschizi Gmail-ul, tot tu creezi evenimentul în Calendar, tot tu trimiți mesajul.

**Gemini Act** pleacă de la o premisă diferită: agentul chiar face acțiunea, nu doar îți spune ce ar trebui să faci.

## Ce este, concret

E un agent construit pe **Google ADK**, care trăiește direct în **Google Chat**. Îi scrii un DM sau îl @-menționezi într-un spațiu de echipă, iar el:

- citește și trimite mailuri (Gmail),
- caută, citește și organizează fișiere (Drive),
- creează și actualizează evenimente (Calendar),
- interoghează seturi de date (BigQuery),
- caută locații, calculează rute, verifică vremea (Maps),
- citește și scrie în Cloud Storage,
- și interacționează cu Chat-ul însuși — în numele tău sau în numele aplicației, după caz.

Nu e un bot generic care „știe de toate” — ia acțiuni reale, cu permisiunile *tale*, pentru că autentificarea e per-utilizator (OAuth cu trei părți). Practic, agentul nu poate face nimic ce tu însuți n-ai avea voie să faci în Workspace.

## De ce e interesant din punct de vedere tehnic

Trei decizii de arhitectură merită menționate, pentru că răspund la probleme reale, nu la probleme de manual:

**1. Răspunsul e asincron.** Google Chat îți dă ~30 de secunde pentru un răspuns sincron la un webhook — insuficient pentru o buclă de agent care apelează unelte, gândește, mai apelează încă o unealtă. Soluția: serverul confirmă instant primirea evenimentului, iar răspunsul „adevărat" e postat separat, după ce agentul termină de lucrat.

**2. O singură instanță de agent servește pe toată lumea.** În loc să pornească un agent nou per utilizator (scump și greu de scalat), Gemini Act rezolvă token-ul de acces al fiecărui utilizator *la momentul apelului de tool*, nu la pornirea agentului. Rezultat: un singur proces, sesiuni MCP izolate corect între utilizatori.

**3. Poți să-i conectezi propriile tale unelte, live, fără redeploy.** Dai paste la un URL de server MCP (sau la un bloc JSON de configurare, genul celor pentru Claude Desktop) direct în chat, iar agentul îl testează, îi cere lista de unelte, și — dacă totul e în regulă — le adaugă în conversația *ta*, fără să afecteze pe nimeni altcineva. E genul de flexibilitate care, altfel, ar însemna un ticket la echipa de platformă.

## Guardrails, nu doar funcționalitate

Un agent care poate trimite mailuri și șterge fișiere e la fel de periculos pe cât e de util, dacă nu are frâne. Câteva reguli sunt construite direct în prompt și în arhitectură, nu lăsate la latitudinea modelului:

- **Confirmare obligatorie** înainte de orice acțiune care scrie, trimite, partajează sau șterge ceva.
- **Rezultatele din unelte externe (inclusiv cele conectate de utilizator) sunt tratate ca date, nu ca instrucțiuni** — o apărare directă împotriva prompt injection.
- **Fără acces la shell sau filesystem** — cea mai „puternică" și cea mai riscantă capacitate posibilă e lăsată deliberat pe dinafară.
- Serverele MCP externe acceptate sunt doar **remote, peste HTTPS** — un config care ar rula o comandă locală (`npx ...`) e refuzat direct, ca să nu execuți cod ales de un mesaj de chat în interiorul containerului agentului.

## Ce înseamnă, de fapt

Diferența dintre „AI care te ajută să scrii un mail” și „AI care trimite mailul” pare mică, dar schimbă complet ce poți automatiza într-o organizație. Nu mai e vorba de productivitate individuală marginală — e vorba de a scoate agentul din rolul de asistent și a-l pune să facă parte din flux.

Rămâne, desigur, întrebarea pe care orice echipă care construiește așa ceva trebuie să și-o pună serios: unde tragem linia între „util” și „prea multă putere într-un singur mesaj de chat”? Răspunsul lui Gemini Act — permisiuni per-utilizator, confirmare pe acțiuni destructive, fără shell — e un punct de plecare solid, nu un răspuns definitiv.

---

*Construit pe Google ADK, Cloud Run și Firestore, cu unelte Workspace expuse via Model Context Protocol.*
