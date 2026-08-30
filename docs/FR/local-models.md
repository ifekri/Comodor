# Des modèles sur votre propre machine

Comodor peut télécharger un modèle, le garder sur votre disque et l'y exécuter —
pas de clé, pas de compte, et il continue de fonctionner le câble réseau
débranché.

```bash
comodor local list                       # what you can run, and what is here
comodor local get qwen2.5-coder-7b-q4    # download it, with a progress bar
comodor local use qwen2.5-coder-7b-q4    # make it the one the agent talks to
```

La même liste est dans le navigateur sous **Admin → Local LLM**, avec le même
téléchargement, la même progression et les mêmes boutons.

## Comment c'est assemblé, et pourquoi ce n'est pas lent

Tout ce qui est crédible fait la même chose — Ollama, LM Studio, llama.cpp,
vLLM — et Comodor aussi : **l'inférence tourne dans un processus séparé qui
parle une API compatible OpenAI, et le modèle reste chargé dans ce processus
entre les requêtes.**

Trois raisons, toutes liées à l'agent qui reste réactif :

**Le GIL.** La génération est une longue boucle limitée par le processeur.
L'exécuter dans le processus propre de Comodor, et chaque autre fil —
l'interface qui se redessine, un outil qui se termine, le bus d'événements —
attend derrière elle. Dans un autre processus, c'est le problème d'un autre
cœur.

**Le chargement coûte cher et doit n'arriver qu'une fois.** Lire quatre
gigaoctets sur le disque et les mettre en place prend des secondes à des
dizaines de secondes. Charger à chaque requête paie ce prix à chaque tour ; un
serveur résident le paie une fois et répond ensuite en millisecondes.

**Un plantage reste là-bas.** Une destruction pour mémoire épuisée sur un modèle
14B tue le serveur de modèle, pas votre session. L'agent signale une erreur de
connexion et la transcription survit.

La conséquence heureuse est qu'il n'y a presque pas de nouveau code : un
serveur local sur `http://127.0.0.1:PORT/v1` *est* un point de terminaison
compatible OpenAI, si bien que le fournisseur existant le pilote sans changer.
Le port est choisi au démarrage du serveur, voilà pourquoi le fournisseur
`local` ne porte pas d'URL dans la configuration — une URL écrite là serait
fausse la fois suivante.

Le serveur démarre à votre **premier message**, pas au lancement. Charger
quatre gigaoctets chaque fois que vous lanciez `comodor` — y compris les fois
où vous ne demandiez rien au modèle — serait un écran vide sans raison.

## Ce dont vous avez besoin

Le fichier du modèle, que Comodor télécharge, et quelque chose pour l'exécuter.
Comodor utilise ce qu'il trouve :

```bash
brew install llama.cpp          # macOS
winget install llama.cpp        # Windows
                                # Linux: github.com/ggml-org/llama.cpp
```

Ollama ou LM Studio, si l'un des deux tourne déjà, fonctionnent aussi. `comodor
local list` dit franchement quand rien n'est disponible, si bien que vous le
découvrez avant de passer une heure à un téléchargement plutôt qu'après.

## Le téléchargement

Un modèle fait un à neuf gigaoctets par votre ligne domestique, et tout ce qui
concerne le téléchargement est façonné par cela.

**Il reprend.** Les octets vont dans un fichier `.part`. Arrêtez-le, fermez
l'ordinateur portable, perdez la connexion — le prochain `comodor local get`
demande au serveur de continuer à partir de là où ce fichier s'arrête. Le
navigateur affiche `Resume (37%)` au lieu de `Download`.

**Il est vérifié.** Chaque entrée du catalogue porte un nombre d'octets exact et
un SHA-256, et le fichier n'est accepté qu'à la correspondance. Ce n'est pas de
la ceinture et des bretelles : un GGUF tronqué n'est *pas* visiblement cassé —
il se charge, puis le modèle produit du charabia, et vous passez une soirée à
vous demander pourquoi un modèle réputé est inutilisable. Un fichier qui échoue
est supprimé au lieu d'être laissé à retrouver plus tard et à demi cru.

**Il est observable.** Dans le terminal, une barre avec les quatre chiffres qui
répondent à la question posée :

```
qwen2.5-coder-7b-q4 ━━━━━━━━━━━━━━╸────────  38.2%  1.7/4.4 GB  8.9 MB/s  0:05:12
```

Dans le navigateur, les mêmes chiffres sous une barre sur la carte du modèle,
mis à jour depuis le flux d'événements plutôt que par scrutation.

## Où vont les fichiers

Un répertoire, partagé par chaque projet de la machine — le même modèle dans
trois checkouts serait sinon trois copies des mêmes octets.

```bash
comodor local where
```

`comodor local remove <id>` en supprime un, et dit combien d'espace est revenu.

## Ajouter un modèle à la liste

La liste est un fichier JSON, si bien qu'un nouveau modèle est une édition plutôt
qu'une version. Le terminal et le navigateur le repèrent tous les deux.

```json
{
  "id": "my-model-q4",
  "name": "My Model 7B",
  "description": "One sentence on what it is good at, and what it is not.",
  "url": "https://huggingface.co/OWNER/REPO/resolve/main/file.gguf",
  "size": 4683074336,
  "sha256": "1664fccab734674a...",
  "context": 32768,
  "parameters": "7B",
  "quantization": "Q4_K_M",
  "needs_ram_gb": 8,
  "license": "apache-2.0",
  "good_at": ["code"],
  "tools": true,
  "vision": false
}
```

`id`, `name`, `url` et `size` sont obligatoires — tout le reste est facultatif,
et tout ce que vous omettez est signalé comme inconnu au lieu d'être deviné. Un
mauvais chiffre ici coûte à quelqu'un un téléchargement et un plantage.

Récupérez la taille et la somme de contrôle depuis l'API plutôt que de les
taper :

```bash
curl -s 'https://huggingface.co/api/models/OWNER/REPO?blobs=true' | python -c \
  "import json,sys;[print(f['rfilename'], f['size'], f.get('lfs',{}).get('sha256')) \
   for f in json.load(sys.stdin)['siblings'] if f['rfilename'].endswith('.gguf')]"
```

Deux règles que le chargeur fait respecter :

- **`https` uniquement.** Un fichier de modèle est un artefact exécutable à tous
  les égards qui comptent, et un fichier récupéré sur un canal que quelqu'un
  peut réécrire en vol n'est pas quelque chose à autoriser parce qu'un catalogue
  l'a demandé.
- **Une mauvaise entrée ne coûte pas la liste.** Un modèle mal formé est ignoré
  et le reste se charge, car l'alternative est un sélecteur vide.

Comodor embarque une copie de la liste et en cherche une plus récente une fois
par jour, en mettant en cache ce qu'il trouve. Sans réseau, il utilise le
cache, et à défaut la copie embarquée — ce qui est tout l'intérêt d'en embarquer
une.

## Ce qu'il ne fera pas

`needs_ram_gb` est vérifié sur votre machine avant que le téléchargement ne
commence, et un modèle qui n'entrera pas le dit au lieu de vous laisser passer
une heure à le découvrir. `comodor local get --yes` passe outre si vous n'êtes
pas d'accord.

Le disque est vérifié de la même façon, avec un dixième laissé en réserve : un
téléchargement qui remplit le dernier octet d'un disque n'échoue pas seulement,
il emporte le reste de la machine avec lui.
