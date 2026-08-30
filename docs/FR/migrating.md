# Venir d'un autre agent

Si vous utilisez déjà **OpenClaw** ou **Hermes**, Comodor propose de rapporter
votre configuration la première fois que vous le lancez.

Vous avez déjà trouvé vos clés API et les avez collées quelque part. Le faire
à nouveau est une mauvaise première impression.

---

## Au premier lancement

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

La question n'apparaît que s'il y a quelque chose à importer.

---

## Ensuite

Installé l'un d'eux plus tard, ou répondu « start fresh » et changé d'avis :

```bash
comodor import              # bring it across
comodor import --dry-run    # say what it would take, change nothing
comodor import --keys-only  # leave the skills and the model
```

Le lancer deux fois est sans danger — la seconde fois il dit qu'il n'y a rien
de nouveau.

---

## Ce qui vient

| | |
|---|---|
| **Clés API** | toute la lassitude du travail. Depuis leur `.env`, et depuis le JSON inliné d'OpenClaw |
| **Le modèle** | si Comodor peut l'héberger |
| **Compétences** | les deux outils écrivent le même format ouvert, donc ce sont des fichiers à copier |

Trois règles tout du long, car cela lit les fichiers d'un autre programme :

- **Rien n'est écrasé.** Une clé déjà configurée ici l'emporte ; l'import
  comble les manques.
- **Rien n'est déplacé.** Chaque lecture est une lecture. L'autre outil
  continue de fonctionner exactement comme avant.
- **Un fichier malformé est ignoré, pas fatal.** La moitié de la valeur, c'est
  que cela tourne sur une machine dont l'autre agent est dans un état étrange.

---

## Ce qui ne vient pas, et pourquoi

**Leur mémoire.** Dit à voix haute plutôt que sauté en silence :

```
not imported: MEMORY.md — its memory is prose; this agent's is lessons with
confidence and evidence, and inventing those would poison recall
```

Le cerveau de Comodor, ce sont des leçons avec une confiance, des preuves et
une décrue, apprises de vos corrections. Un `MEMORY.md` est de la prose.
Importer l'un comme l'autre inventerait des confiances que personne n'a
mesurées et remplirait le rappel d'entrées jamais méritées. Vous obtiendriez un
agent pire qui ressemblerait à un agent mieux informé.

**Personas, messagerie, synthèse vocale.** Comodor n'a pas d'équivalent, et un
réglage importé dans le vide est pire que pas de réglage.

**Une clé rangée ailleurs.** OpenClaw permet qu'une clé soit une référence à un
fichier ou à une commande. Ceux-là signifient quelque chose sur la machine pour
laquelle ils ont été écrits et rien ici, donc ils sont signalés plutôt que
devinés.

---

## Compétences, et une chose à savoir

Les compétences importées sont placées dans un espace de noms — `review`
devient `openclaw-review` — pour qu'un import ne puisse jamais remplacer
discrètement l'une des vôtres.

Un dossier de compétence est copié fichier par fichier, et **un dossier
contenant un lien sortant de lui-même est refusé**. Une compétence est un
fichier dont le contenu est lu dans une invite, donc un symlink vers
`~/.ssh/id_rsa` posé dans le répertoire de compétences d'un autre programme
aurait sinon été copié puis envoyé à un modèle. Refusé, et nommé :

```
not imported: the skill sneaky — it contains a link out of that folder
```

---

## Où il cherche

| | |
|---|---|
| OpenClaw | `~/.openclaw`, `~/.clawdbot`, `~/.moltbot` |
| Hermes | `~/.hermes` |

Les anciens répertoires d'OpenClaw sont encore sur de vraies machines — il a
été renommé deux fois — donc les trois sont vérifiés.

Pour qu'il cesse de chercher du tout :

```bash
export COMODOR_NO_IMPORT=1
```

---

## Voir aussi

- [Premiers pas](getting-started.md) — le reste du premier lancement
- [Configuration](configuration.md) — où arrivent les réglages importés
- [Compétences](skills.md) — quoi faire de celles qui sont venues
