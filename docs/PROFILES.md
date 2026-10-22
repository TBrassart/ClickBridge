# Gestion des profils

Les profils permettent d'adapter les actions clavier de ClickBridge à différentes applications. Tu peux créer des profils distincts, les exporter pour les sauvegarder, puis les importer pour les réutiliser.

Les libellés des commandes peuvent varier selon la version de ClickBridge. Ce guide décrit les opérations à effectuer dans la section de configuration.

## 1. Créer un profil

1. Ouvre ClickBridge.
2. Accède à la configuration et à la gestion des profils.
3. Crée un nouveau profil.
4. Attribue-lui un nom explicite, par exemple `MyWhoosh` ou `Rouvy`.
5. Configure les actions clavier associées aux événements disponibles.
6. Si le profil doit être associé automatiquement à une application, renseigne le nom de son exécutable lorsque cette option est proposée.
7. Enregistre le profil et sélectionne-le pour effectuer un test.

### Conseils de configuration

- Choisis un nom facile à identifier.
- Vérifie chaque correspondance entre une commande physique et une touche.
- Teste les touches spéciales, notamment Entrée, Espace, Échap et les flèches directionnelles.
- Si la capture directe d'une touche ne fonctionne pas, utilise une méthode de sélection explicite si ta version la propose.
- Vérifie que les actions configurées sont compatibles avec l'application cible.

## 2. Sélectionner le profil utilisé

ClickBridge peut proposer plusieurs profils pour différents usages.

Si la sélection manuelle est disponible, choisis le profil correspondant à ton application.

Si le mode automatique est disponible, vérifie que l'association entre le profil et l'exécutable de l'application est correctement renseignée.

Par exemple, un profil associé à `MyWhoosh.exe` ne sera pas nécessairement sélectionné automatiquement si le nom configuré ne correspond pas au processus réellement exécuté.

Vérifie également le profil par défaut, lorsqu'il est configuré, car il peut être utilisé lorsqu'aucune association automatique ne correspond.

## 3. Exporter un profil

L'export permet de conserver une copie d'un profil ou de le transférer vers une autre installation compatible.

1. Ouvre la gestion des profils.
2. Sélectionne le profil à exporter, si l'interface le demande.
3. Utilise la fonction d'export proposée par ta version.
4. Choisis un emplacement facile à retrouver.
5. Vérifie que le fichier a bien été créé.

Donne au fichier un nom explicite, par exemple `MyWhoosh-profil.json`, si le format d'export utilisé est JSON.

Conserve une copie de tes profils avant toute modification importante.

**Attention :** l'export d'un profil et l'export de la configuration complète sont deux opérations différentes. Vérifie ce que contient le fichier généré avant de le partager ou de l'utiliser pour restaurer des réglages.

## 4. Importer un profil

Pour importer un profil précédemment exporté :

1. Ouvre la gestion des profils dans ClickBridge.
2. Utilise la fonction d'import disponible.
3. Sélectionne le fichier à importer.
4. Vérifie que l'import s'est terminé sans erreur.
5. Contrôle le nom du profil, ses correspondances clavier et ses éventuelles associations à une application.
6. Sélectionne le profil et teste son fonctionnement.

### Si un profil portant le même nom existe déjà

Vérifie le comportement proposé par l'application avant de poursuivre. Selon la version, un conflit peut nécessiter de choisir un autre nom ou de décider si un profil existant doit être remplacé.

Ne remplace pas un profil fonctionnel sans en avoir conservé une copie si tu souhaites pouvoir revenir en arrière.

### Précautions

N'importe pas de fichier de provenance inconnue sans en vérifier le contenu. Un profil mal configuré peut déclencher des actions clavier inattendues dans l'application active.

## 5. Restaurer un profil précédemment exporté

Si tu souhaites revenir à une ancienne version d'un profil :

1. Retrouve le fichier exporté précédemment.
2. Si nécessaire, exporte une copie du profil actuellement utilisé.
3. Importe le fichier correspondant à la version que tu souhaites récupérer.
4. Résous les éventuels conflits de nom.
5. Vérifie les actions et sélectionne le profil restauré.
6. Effectue un test avant de reprendre une utilisation normale.

Cette procédure restaure les informations présentes dans le fichier exporté. Elle ne restaure pas nécessairement les paramètres généraux de ClickBridge.

## 6. Restaurer la configuration complète

La restauration d'un profil ne doit pas être confondue avec la restauration de la configuration complète de ClickBridge.

Avant de restaurer une configuration :

- conserve une copie des profils importants ;
- vérifie que la sauvegarde correspond à une version compatible ;
- identifie les paramètres susceptibles d'être remplacés ;
- utilise uniquement une procédure de restauration effectivement proposée par ta version.

Ne supprime pas manuellement des fichiers de configuration pour tenter de réinitialiser l'application.

Si ClickBridge ne propose pas de fonction de restauration complète dans ta version, utilise les fonctions d'export disponibles et demande conseil avant de modifier les fichiers internes.

## 7. Problèmes courants

### Le profil n'apparaît pas après l'import

Vérifie le fichier sélectionné, le résultat de l'import et les éventuels messages d'erreur. Assure-toi que le fichier provient d'un export compatible avec ClickBridge.

### Le mauvais profil est utilisé

Vérifie le profil actif, le mode de sélection et l'association avec l'exécutable de l'application.

### Une touche ne fonctionne pas

Vérifie le mapping de l'événement, la prise en charge de la touche et le comportement de l'application cible.

### Tu as remplacé un profil par erreur

Si tu possèdes un export antérieur, importe-le après avoir conservé une copie de la version actuelle.

## Voir aussi

- [Comprendre les périphériques, composants et profils](CONCEPTS.md)
- [Dépannage](SUPPORT.md)
- [Installation](INSTALLATION.md)
