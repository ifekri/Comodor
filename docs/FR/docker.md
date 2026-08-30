# Dans Docker

L'agent, son navigateur et tout ce dont il a besoin, dans un seul conteneur.

```bash
git clone -b docker https://github.com/ifekri/Comodor.git comodor-docker
cd comodor-docker
export ANTHROPIC_API_KEY=…        # or OPENAI_API_KEY, OPENROUTER_API_KEY, …
docker compose up
```

Il construit l'image la première fois, puis affiche l'adresse :

```
  Comodor is at  http://127.0.0.1:8765/?token=…
  Working in     /work
```

Ouvrez le lien. Un nouveau jeton à chaque exécution : utilisez celui de
*cette* exécution.

Ou sans rien cloner :

```bash
docker run --rm -it -p 127.0.0.1:8765:8765 \
  -e ANTHROPIC_API_KEY \
  -v "$PWD:/work" \
  ghcr.io/ifekri/comodor:latest
```

---

## Une clé n'est pas facultative ici

L'interface navigateur n'offre aucun moyen d'en saisir une, si bien que sans clé
le conteneur indique ce qui manque et s'arrête, au lieu de servir une URL qui
échoue dès la première tâche.

Compose transmet celle de ces variables qui est définie dans votre shell, sans
l'écrire dans l'image ni dans le fichier compose :

```
ANTHROPIC_API_KEY   OPENAI_API_KEY   OPENROUTER_API_KEY   DEEPSEEK_API_KEY
GEMINI_API_KEY      GROQ_API_KEY     XAI_API_KEY          MISTRAL_API_KEY
XIAOMI_API_KEY
```

Plutôt un fichier que l'historique de votre shell ? Placez-le dans un `.env` à
côté du fichier compose — compose le lit, et il est ignoré par git.

---

## Où il travaille

Tout ce que l'agent peut toucher est le dossier `work/` à côté du fichier
compose. Pointez-le ailleurs :

```yaml
volumes:
  - "/path/to/your/project:/work"
```

Ce qu'il apprend — le cerveau, vos corrections, les transcriptions de session —
vit dans un volume nommé, si bien qu'il survit à `docker compose down` et est
oublié par `docker compose down -v`.

---

## Qui peut l'atteindre

```yaml
ports:
  - "127.0.0.1:8765:8765"
```

**Le `127.0.0.1` de gauche est tout le modèle de sécurité.** Retirez-le et le
port se retrouve sur toutes les interfaces de la machine — et ce port est un
shell.

Dans le conteneur, Comodor écoute sur `0.0.0.0`, ce qui n'est pas un oubli : un
conteneur possède son propre espace de noms réseau, si bien qu'écouter sur
l'interface locale à l'intérieur cache le port à la machine qui l'exécute. Qui
peut réellement l'atteindre est décidé par la façon dont le port a été publié,
et la bannière le dit.

---

## Ce que le conteneur peut faire

```yaml
cap_drop: [ALL]
security_opt:
  - no-new-privileges:true
```

Il exécute des commandes shell, donc le conteneur est ce qui s'interpose entre
elles et votre machine. Il ne reçoit rien dont il n'a pas besoin, et tourne
comme un utilisateur non root.

---

## Épingler une version

```yaml
args:
  COMODOR_VERSION: "0.9.0"
```

Épinglée par défaut pour qu'une reconstruction soit reproductible. Pour la
dernière version publiée à la place :

```bash
docker compose build --build-arg COMODOR_VERSION=
```

---

## Exécuter autre chose dedans

```bash
docker compose run --rm comodor comodor doctor
docker compose run --rm comodor sh
```

Aucun argument, ou des arguments commençant par un tiret, signifient « lancer
l'interface web avec ces options ». Tout le reste est une commande à exécuter à
la place.

---

## Ce qui n'est pas dans le conteneur

**Votre écran.** Le [contrôle du bureau](computer.md) pilote la machine sur
laquelle Comodor tourne, et dans un conteneur c'est une machine sans écran.
L'outil n'y est pas proposé.

Le [navigateur](browser.md) fonctionne, lui — Chromium et ses polices sont dans
l'image.

---

## S'il ne démarre pas

**Rien sur `localhost:8765`** — vérifiez que le port est publié :
`docker compose ps`.

**Il se termine immédiatement** — lisez le journal. Dans presque tous les cas,
aucun fournisseur n'est configuré ; le message dit quoi définir.

**`exec /usr/local/bin/comodor-start: no such file or directory`** — un
checkout CRLF. Corrigé dans la branche avec un `.gitattributes` ; si vous le
voyez, faites un pull.

---

## Voir aussi

- [Depuis un navigateur](web.md) — l'interface que vous allez utiliser
- [Sécurité](safety.md) — ce que l'agent peut faire dans le conteneur
