# Depuis un navigateur

Le même agent, dans un onglet de navigateur. Sur cette machine, ou sur un
serveur que vous rejoignez en SSH.

```bash
comodor web
```

```
   ______                          __
  / ____/___  ____ ___  ____  ____/ /___  _____
 / /   / __ \/ __ `__ \/ __ \/ __  / __ \/ ___/
/ /___/ /_/ / / / / / / /_/ / /_/ / /_/ / /
\____/\____/_/ /_/ /_/\____/\__,_/\____/_/

  it learns the way you correct it   0.9.0  ·  claude-sonnet-5

  Comodor is at  http://127.0.0.1:8765/?token=EYhO9St_VTy95k4gHtJytb
  Working in     /home/you/projects/api-server

  Only this machine can reach it. Ctrl-C to stop.
```

Ouvrez le lien. Le jeton est dedans.

---

## Options

```bash
comodor web --port 9000
comodor web --no-browser            # do not open one for me
comodor web --token mytoken         # a fixed token
comodor web --host 0.0.0.0          # reachable from elsewhere — read below
```

---

## Le jeton

Un nouveau à chaque exécution, si bien qu'une URL d'hier n'est pas un moyen
d'entrer aujourd'hui. Il arrive dans l'URL, est échangé contre un cookie, et
toute requête ultérieure est autorisée par ce cookie.

Pour le garder stable d'un redémarrage à l'autre :

```bash
export COMODOR_WEB_TOKEN=something-long-and-random
```

Quiconque possède le jeton a un shell sur cette machine. Traitez-le comme tel.

---

## Écouter au-delà de l'interface locale

`--host 0.0.0.0` place l'interface sur toutes les interfaces de la machine.
**Ce port est un shell.** Comodor le dit plutôt que de supposer que vous le
vouliez :

```
  Listening on every address on this machine.
  Anyone who can reach this port can run commands as you.
```

Mieux, quand l'agent est sur un serveur : le laisser sur l'interface locale et
passer par un tunnel.

```bash
ssh -N -L 8765:127.0.0.1:8765 you@server
```

Ouvrez ensuite `http://127.0.0.1:8765` localement. Le port n'est jamais exposé
et SSH fait l'authentification.

---

## Le voir utiliser un écran

Si l'agent pilote un bureau, l'image qu'il a regardée apparaît dans l'interface
avec un marqueur là où il a agi :

```
┌────────────────────────────────────────────┐
│                                            │
│   [ the screen the model saw ]      ✛      │
│                                            │
│   clicking Save                            │
└────────────────────────────────────────────┘
```

C'est là tout l'intérêt. La superposition à l'écran se dessine sur la machine
pilotée, ce qui ne sert à rien quand cette machine est un serveur ou un
conteneur — le panneau est la façon de regarder depuis ailleurs.

L'image est récupérée une fois par image affichée depuis `/api/screen`, et non
transportée dans le flux d'événements : une capture d'écran pèse environ un
mégaoctet, et un navigateur qui relirait le journal d'événements téléchargerait
chaque image qu'il a jamais vue.

[Utiliser votre écran](computer.md).

---

## Ce qu'il ne fera pas

**Démarrer sans fournisseur.** Il peut basculer entre des fournisseurs déjà
configurés, mais il n'y a nul part où saisir une clé, et un onglet de navigateur
serait un mauvais endroit pour cela. Plutôt que de servir une URL qui échoue dès
la première tâche, il dit ce qui manque et s'arrête :

```
Comodor has no provider configured, and the browser interface has no way to
add one.

  In Docker, pass a key in as an environment variable:
    -e ANTHROPIC_API_KEY=...    -e OPENAI_API_KEY=...
  or mount a config file at ~/.comodor/config.json.
  Anywhere with a terminal, `comodor setup` asks a few questions.
```

Dans un terminal, il pose les questions de configuration à la place. Dans un
conteneur, il affiche toujours le message — un conteneur a un terminal qu'un
utilisateur y soit attaché ou non, et un conteneur détaché attendrait sinon
pour toujours une réponse que personne ne peut donner.

**Élargir ce que l'agent peut toucher.** L'approbation automatique des écritures
et des commandes est affichée dans Admin et ne peut pas y être modifiée. Les
demandes d'autorisation offrent déjà ce choix action par action, devant la
personne qui vivra avec ; une page accessible à quiconque détient le lien est
le mauvais endroit pour en faire une politique permanente. Changez cela là où
Comodor a été démarré — voir [Sécurité](safety.md).

---

## Ce qui est à l'écran

**La conversation**, en flux au fil de son arrivée, avec le code balisé gardé
comme code et chaque appel d'outil sous forme de ligne que vous pouvez ouvrir
pour voir ce qu'il a réellement fait.

**La liste des discussions**, à gauche. Chaque conversation est écrite dans
`~/.comodor/sessions` — le même dossier que le terminal utilise, si bien qu'une
discussion commencée à l'invite est ouvrable dans le navigateur, et inversement.
La recherche regarde à l'intérieur, pas seulement dans les titres.

**Admin**, le second onglet, qui répond à la question « que cette chose
s'apprête-t-elle à faire à ma machine » :

| | |
|---|---|
| Modèle | quel fournisseur et quel modèle répond, et la bascule entre ceux pour lesquels vous avez des clés |
| Mode d'exécution | le mode, s'il continue tout seul, et les quatre plafonds — contexte, étapes, temps, dépenses |
| Autorisations | ce qu'il peut faire sans demander, ce qu'il demandera, et ce qui a été accordé durant cette session |
| Ce qu'il a appris | règles, leçons, compétences, tâches, et combien ont réussi |
| Outils | chaque outil à sa portée, codé par couleur selon le risque, plus vos compétences et les éventuels serveurs MCP |
| Cette machine | version, Python, et où vivent les réglages, les discussions et le cerveau |

**La bande d'état** en bas : si la page est connectée, le dossier de travail,
le remplissage du contexte, ce que la session a coûté, et combien de règles
apprises sont en vigueur.

**Le panneau d'écran**, quand l'agent en pilote un — la dernière image qu'il a
regardée, avec un marqueur là où il s'apprête à cliquer. Voir [Utiliser votre
écran](computer.md).

---

## Clavier

| | |
|---|---|
| `Enter` | envoyer |
| `Shift`+`Enter` | nouvelle ligne |
| `Esc` | arrêter la tâche en cours, ou fermer la barre latérale |
| `Ctrl`/`⌘`+`K` | chercher dans les discussions |
| `Ctrl`/`⌘`+`B` | afficher ou masquer la barre latérale |
| `/` | aller à la zone de message |

---

## Sur un téléphone

La même page. En dessous de 900 pixels, la liste des discussions devient un
tiroir par-dessus la conversation plutôt qu'une colonne à côté d'elle, car 292
pixels de barre latérale sur un écran de 390 pixels ne laissent rien d'assez
large pour y lire du code. Touchez en dehors, appuyez sur `Esc`, ou utilisez le
bouton de fermeture pour la ranger.

Rejoignez-la depuis votre téléphone comme vous rejoindriez n'importe quoi
d'autre sur votre machine — un tunnel SSH, pas une écoute publique.
[Écouter au-delà de l'interface locale](#binding-to-more-than-loopback)
explique pourquoi.

---

## Écrire dans n'importe quelle langue

Tapez en persan, en arabe ou en hébreu et la zone de message s'inverse au fil de
la frappe ; les réponses dans ces langues sont alignées de droite à gauche à
leur arrivée. Rien à configurer et pas de réglage de langue : chaque message est
jugé pour lui-même, si bien qu'une conversation qui passe d'une langue à une
autre suit le mouvement.

Le jugement se fait en comptant plutôt qu'à la première lettre, et c'est ce qui
fait tomber juste les deux cas délicats — une phrase persane qui s'ouvre sur un
nom de paquet reste persane, et une phrase anglaise citant un mot persan reste
anglaise. Le code, les chemins et les URL sont alignés de gauche à droite à
l'intérieur d'un paragraphe de droite à gauche, à la place qui est la leur.

Le texte en écriture arabe est composé en Vazirmatn, qui voyage dans le paquet
plutôt que d'être récupéré auprès d'un hébergeur de polices : cela doit
fonctionner sur une machine qui ne peut pas atteindre Internet. Cela s'applique
aux caractères en écriture arabe et à rien d'autre, de sorte qu'une ligne qui
mêle persan et identifiant anglais reçoit la bonne fonte pour chacun.

---

## Clair et sombre

Suit le système par défaut ; le soleil en haut à droite bascule, et le choix est
retenu dans ce navigateur.

---

## Dans Docker

```bash
docker compose up
```

et ouvrez l'adresse qu'il affiche. [Docker](docker.md).

---

## Voir aussi

- [Docker](docker.md) — la même chose dans un conteneur
- [L'interface](interface.md) — la version terminal
- [Sécurité](safety.md) — les autorisations que l'onglet Admin signale
- [Utiliser votre écran](computer.md) — ce que vous montre le panneau d'image
