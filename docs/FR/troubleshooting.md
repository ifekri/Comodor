# Dépannage

## Commencer ici

```bash
comodor doctor
```

Il vérifie le fichier de configuration et ses permissions, le fournisseur, le
modèle, la limite de dépenses, le cerveau, l'index de recherche, vos
compétences, les fichiers résiduels, les serveurs MCP, et l'existence d'une
version plus récente.

```bash
comodor doctor --fix
```

répare ce qui est réparable. Il ne change jamais rien qu'il n'ait signalé
d'abord.

---

## Il ne démarre pas

**`comodor: command not found`, juste après l'installation** — l'installateur
l'a mis sur votre `PATH`, mais un processus enfant ne peut pas changer
l'environnement du shell qui l'a lancé. Chaque terminal *nouveau* fonctionne
déjà. Pour celui dans lequel vous êtes, l'installateur a affiché la ligne à
coller ; ou :

```bash
export PATH="$HOME/.local/bin:$PATH"
```

**`comodor: command not found`, dans un nouveau terminal** — cela, c'est un vrai
problème. `python -m comodor` confirme s'il est installé, et
`ls ~/.local/bin/comodor` où il devrait être.

**`No provider is configured`** — lancez `comodor setup`, ou exportez une clé :

```bash
export ANTHROPIC_API_KEY=sk-ant-…
```

**Python trop ancien.** Comodor exige 3.11 ou plus récent. Vérifiez avec
`python --version`.

---

## Un paramètre semble ne rien faire

Comodor vous le dit quand il en refuse un :

```
config: agent.max_steps must be a whole number; keeping 0
config: this project cannot set safety, computer — only your own can
```

Si rien n'est dit et qu'il reste sans effet, vérifiez quelle couche l'emporte :

```
/settings          # what is actually loaded
```

```bash
comodor doctor     # the same, plus where every file is
```

Un `--model` sur la ligne de commande l'emporte sur votre fichier de
configuration, et une clé dans votre environnement l'emporte sur celle du
fichier. C'est délibéré — [Configuration](configuration.md#what-wins).

---

## `/save` n'a pas enregistré ce à quoi je m'attendais

C'est voulu. Il écrit **uniquement ce que vous avez choisi** — pas les réglages
d'un dépôt, pas une clé que vous gardez dans votre environnement, pas une option
passée pour une seule exécution.

Pour vous approprier le réglage d'un dépôt, définissez-le d'abord vous-même
(`/model x`), puis enregistrez.

---

## Les requêtes échouent

**`401` ou `invalid api key`** — la clé est fausse, expirée, ou appartient à un
autre fournisseur. `comodor doctor` montre quel fournisseur est actif.

**`404 model not found`** — ce fournisseur ne dessert pas cet identifiant de
modèle. `/model` liste ce qu'il offre réellement.

**Délais dépassés.** Un modèle local sur une machine modeste peut réellement
prendre des minutes. Augmentez `providers.<name>.timeout`.

**Il s'arrête tôt.** Regardez `stopped`. `max_steps` et `budget` sont des
plafonds qui font leur travail, pas des échecs. Augmentez-les pour une exécution
avec `--max-steps`, ou de façon permanente sous `agent`.

---

## La limite de dépenses ne fonctionne pas

Elle ne peut probablement pas l'être, et Comodor le dit. Voir
[Coût — quand la limite ne peut pas se déclencher](cost.md#when-the-limit-cannot-fire).

---

## L'outil navigateur

**« no browser found »** — installez Chrome, Chromium, Edge ou Brave, ou
définissez `browser.executable`. Sans aucun, `browse` bascule vers un navigateur
en mode texte qui répond tout de même à la plupart des questions sur une page.

**Je veux le voir travailler** — `browser.headless: false`.

**Il a besoin d'une connexion que j'ai déjà** — démarrez votre propre navigateur
avec un port DevTools et définissez `browser.port`, pour qu'il utilise cette
session au lieu qu'on lui remette votre profil.

---

## L'outil écran

**Il n'est pas dans la liste des outils.** Soit cette plateforme n'a pas de
backend — Windows uniquement, pour l'instant — soit `computer.enabled` est
faux. Demandez :

```
/computer
```

**Les clics tombent au mauvais endroit.** Cela ne devrait pas arriver : la prise
en compte des DPI est déclarée avant la lecture de toute métrique d'écran. Si
cela arrive, signalez-le avec l'échelle et la résolution de votre écran. C'est
un vrai bogue.

**Il s'est arrêté tout seul.** La souris est allée dans un coin de l'écran, ce
qui met fin à l'autorisation exprès. `/computer 15m` en démarre une autre.

**Le texte arrivé n'est pas celui qu'il a tapé.** L'application l'a réécrit — le
Notepad de Windows 11 corrige automatiquement pendant la frappe. Ce n'est pas un
bogue de Comodor, et il le dit à chaque `type`.
[Plus de détails](computer.md#typed-is-not-the-same-as-arrived).

---

## L'interface web

**Il refuse de démarrer.** Aucun fournisseur n'est configuré, et l'interface
navigateur n'offre aucun moyen d'en ajouter un. Le message nomme quoi définir.

**« Unauthorised ».** Un nouveau jeton est généré à chaque exécution — utilisez
l'URL de *cette* exécution, ou définissez `COMODOR_WEB_TOKEN` pour le garder
stable.

**Dans Docker, rien sur `localhost:8765`.** Vérifiez que le port est publié en
`127.0.0.1:8765:8765`. [Docker](docker.md).

---

## Quelque chose est lent

**La première requête d'une session.** Rien n'est encore en cache ; la deuxième
est bien plus rapide.

**La réflexion après chaque tâche.** Un appel au modèle. Utilisez
`learning.reflect_model` pour en avoir un moins cher, ou `reflect: false`.

**Les captures d'écran.** Environ 80 ms pour en prendre une, plus le regard du
modèle dessus. Baissez `computer.screenshot_tokens` si vous arrivez encore à
lire le résultat.

---

## Repartir de zéro

```bash
comodor uninstall --dry-run     # what would go, named
comodor uninstall               # do it
```

Ou juste le cerveau, en gardant vos réglages :

```bash
rm ~/.comodor/brain.db
```

---

## Signaler un problème

Joignez :

```bash
comodor --version
comodor doctor
```

`doctor` masque votre clé. Lisez quand même la sortie avant de la coller.

- Problèmes : <https://github.com/ifekri/Comodor/issues>
- Quelque chose de sensible : [SECURITY.md](../SECURITY.md)
