# Le vrai navigateur

Pas un simple récupérateur de pages. Un navigateur réellement installé — il
exécute JavaScript, conserve les cookies et sait se connecter.

---

## Ce qu'il utilise

Chrome, Chromium, Edge ou Brave, selon ce qui se trouve sur la machine. **Rien
n'est téléchargé.** Il en lance un dans un profil qui lui est propre, connecté à
rien, et le ferme à la fin de la session.

Si aucun n'est installé, `browse` bascule vers un navigateur en mode texte qui
répond tout de même à la plupart des questions sur une page. Les deux
s'appellent `browse`, car choisir entre deux outils nommés « navigateur » est un
tour que le modèle ne devrait pas avoir à dépenser.

---

## Ce qui revient

Pas une capture d'écran. Le titre, le texte lisible, et une **liste numérotée
des contrôles réellement affichés à l'écran** :

```
  Sign in — Example
  ─────────────────────────────────────────────
  Sign in to your account. New here? Create one.

  [1]  textbox   Email
  [2]  textbox   Password
  [3]  button    Sign in
  [4]  link      Forgot your password?
```

Le modèle agit sur l'un d'eux via son numéro. Cette liste est filtrée pour ne
conserver que ce qui est visible, nommé, à l'écran et non dupliqué — ce qui est
beaucoup plus compact que l'arbre d'accessibilité et, en mesuré, plus compact
qu'une capture d'écran de la même page.

Une capture d'écran uniquement quand la question est visuelle — mise en page,
style, un graphique — parce qu'une image coûte le même prix à chaque fois et ne
peut être réduite.

---

## Verbes

| | |
|---|---|
| `open` | aller à une URL |
| `click` | un contrôle, par son numéro |
| `type` | dans un champ, par son numéro |
| `scroll` | vers le haut ou vers le bas |
| `back` | la page précédente |
| `read` | relire la page, après un changement |
| `look` | une capture d'écran, quand la question porte sur l'apparence |
| `script` | exécuter JavaScript et récupérer sa valeur |

---

## Le voir travailler

```json
{ "browser": { "headless": false } }
```

Une fenêtre visible, pour voir ce qu'il fait.

> Ce paramètre était autrefois ignoré — `browser` n'était pas enregistré comme
> section de configuration, si bien que tout réglage `browser` ne faisait
> silencieusement rien. Corrigé en 0.9.0.

---

## Utiliser une session où vous êtes déjà connecté

Plutôt que de remettre votre profil, démarrez votre propre navigateur avec un
port DevTools et pointez Comodor vers lui :

```bash
chrome --remote-debugging-port=9222
```

```json
{ "browser": { "port": 9222 } }
```

Il se rattache à ce navigateur et utilise les onglets et les cookies déjà
présents. Fermez le port quand vous avez terminé — n'importe quoi sur votre
machine peut l'utiliser.

---

## Tous les paramètres

```json
{
  "browser": {
    "executable": "",
    "headless": true,
    "width": 1280,
    "height": 800,
    "port": 0
  }
}
```

| | |
|---|---|
| `executable` | un navigateur précis. Vide signifie chercher aux endroits habituels |
| `headless` | invisible par défaut, pour ne pas voler le focus |
| `width`, `height` | la fenêtre |
| `port` | se rattacher à un navigateur que vous avez démarré, au lieu d'en lancer un |

Un dépôt ne peut en définir aucun de ces paramètres — `browser.executable`
nomme un binaire à lancer.
[Sécurité](safety.md#what-a-repository-may-set).

---

## `browse` ou `web_fetch` ?

| | |
|---|---|
| `web_fetch` | la page est un document. Il la réduit en texte. Économique |
| `browse` | la page est une application. Il faut JavaScript, une connexion ou un clic |

Le modèle est invité à préférer `web_fetch` et à recourir à `browse` quand
celui-là ne suffira pas.

---

## Dans un conteneur

L'image Docker embarque Chromium et les polices pour l'afficher avec lui. Le
bac à sable propre de Chromium ne peut pas démarrer dans un conteneur dont le
profil seccomp bloque les espaces de noms utilisateur ; Comodor le détecte et
réessaie sans le bac à sable interne — en conservant le confinement du
conteneur, qui est la vraie frontière. [Docker](docker.md).

---

## Sous le capot

Le protocole Chrome DevTools au-dessus d'un WebSocket écrit à la main. Aucune
dépendance : la trame RFC 6455 tient en une centaine de lignes et fait partie
du paquet, de la même manière que le client HTTP et le lecteur SSE.

---

## Voir aussi

- [Ce que l'agent peut faire](tools.md) — les autres outils
- [Utiliser votre écran](computer.md) — quand le travail n'est pas une page web
- [Coût](cost.md) — pourquoi il renvoie du texte plutôt que des images
