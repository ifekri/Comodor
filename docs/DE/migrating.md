# Von einem anderen Agenten kommend

Wenn Sie bereits **OpenClaw** oder **Hermes** benutzen, bietet Comodor an,
Ihr Setup beim ersten Lauf herüberzuholen.

Sie haben Ihre API-Schlüssel längst gefunden und irgendwo eingefügt. Es noch
einmal zu tun, ist ein schlechter erster Eindruck.

---

## Beim ersten Lauf

```
 1/7  You already use OpenClaw
  OpenClaw  1 API key, the model (claude-sonnet-5), 1 skill
  /home/you/.openclaw

  Nothing is moved and nothing already set here is replaced.
  Keys are copied into your config; the other tool keeps working.

  1.  bring it over   keys, model and skills
  2.  keys only       leave the skills and the model
  3.  start fresh     import nothing
```

Die Frage erscheint nur, wenn es etwas zu importieren gibt.

---

## Danach

Eines von ihnen später installiert, oder „start fresh" geantwortet und es sich
anders überlegt:

```bash
comodor import              # bring it across
comodor import --dry-run    # say what it would take, change nothing
comodor import --keys-only  # leave the skills and the model
```

Zweimal laufen zu lassen ist sicher — das zweite Mal sagt es, dass es nichts
Neues gibt.

---

## Was herüberkommt

| | |
|---|---|
| **API-Schlüssel** | die ganze Plackerei. Aus ihrer `.env`, und aus OpenClaws eingebettetem JSON |
| **Das Modell** | falls Comodor es hosten kann |
| **Skills** | beide Werkzeuge schreiben dasselbe offene Format, also sind das Dateien zum Kopieren |

Drei Regeln durchgängig, denn dies liest die Dateien eines anderen Programms:

- **Nichts wird überschrieben.** Ein hier bereits konfigurierter Schlüssel
  gewinnt; der Import füllt Lücken.
- **Nichts wird verschoben.** Jeder Lesezugriff ist ein Lesezugriff. Das andere
  Werkzeug funktioniert genau weiter, wie es es tat.
- **Eine fehlerhafte Datei wird übersprungen, nicht fatal.** Die halbe Wertigkeit
  liegt darin, dass es auf einer Maschine läuft, deren anderer Agent in einem
  seltsamen Zustand ist.

---

## Was nicht, und warum

**Sein Gedächtnis.** Laut ausgesprochen statt im Schweigen übersprungen:

```
not imported: MEMORY.md — its memory is prose; this agent's is lessons with
confidence and evidence, and inventing those would poison recall
```

Comodors Brain sind Lektionen mit einer Konfidenz, Belegen und einem Verfall,
gelernt aus Korrekturen. Eine `MEMORY.md` ist Prosa. Die eine als das andere zu
importieren hieße, Konfidenzen zu erfinden, die niemand gemessen hat, und den
Abruf mit Einträgen zu füllen, die nie verdient wurden. Sie bekämen einen
schlechteren Agenten, der aussah wie ein besser informierter.

**Personas, Nachrichtenversand, Sprachausgabe.** Comodor hat kein Äquivalent,
und eine in nichts importierte Einstellung ist schlimmer als keine Einstellung.

**Ein Schlüssel, der woanders gespeichert ist.** OpenClaw erlaubt, dass ein
Schlüssel eine Referenz auf eine Datei oder einen Befehl ist. Die bedeuten auf
der Maschine, für die sie geschrieben wurden, etwas und hier nichts, also
werden sie gemeldet, statt geraten.

---

## Skills, und eine Sache, die es zu wissen lohnt

Importierte Skills werden namespace-isoliert — `review` wird zu
`openclaw-review` — sodass ein Import nie stillschweigend einen von Ihren
ersetzen kann.

Ein Skill-Ordner wird Datei für Datei kopiert, und **ein Ordner, der einen Link
aus sich heraus enthält, wird verweigert**. Ein Skill ist eine Datei, deren
Inhalt in einen Prompt gelesen wird, also wäre sonst ein Symlink auf
`~/.ssh/id_rsa` im Skills-Verzeichnis eines anderen Programms hineinkopiert und
an ein Modell geschickt worden. Verweigert, und benannt:

```
not imported: the skill sneaky — it contains a link out of that folder
```

---

## Wo es sucht

| | |
|---|---|
| OpenClaw | `~/.openclaw`, `~/.clawdbot`, `~/.moltbot` |
| Hermes | `~/.hermes` |

Die älteren OpenClaw-Verzeichnisse liegen noch auf echten Maschinen — es wurde
zweimal umbenannt —, also werden alle drei geprüft.

Damit es überhaupt nicht mehr sucht:

```bash
export COMODOR_NO_IMPORT=1
```

---

## Siehe auch

- [Erste Schritte](getting-started.md) — der Rest des ersten Laufs
- [Konfiguration](configuration.md) — wo die importierten Einstellungen landen
- [Skills](skills.md) — was man mit den herübergekommenen macht
