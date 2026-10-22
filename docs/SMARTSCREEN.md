# Signature de code et avertissements Windows SmartScreen

ClickBridge est actuellement distribué sans certificat de signature de code éditeur reconnu. Lors du téléchargement ou du lancement de l'installateur, Windows peut donc afficher un avertissement indiquant que l'éditeur est inconnu ou que l'application est peu courante.

Cette page explique pourquoi cet avertissement apparaît et comment vérifier la provenance de l'installateur.

## 1. Pourquoi Windows affiche-t-il cet avertissement ?

La signature de code permet notamment de vérifier l'identité de l'éditeur et de détecter si un fichier signé a été modifié depuis sa signature.

En l'absence d'une signature reconnue, Windows ne peut pas authentifier l'éditeur de ClickBridge au moyen de ce mécanisme.

Windows SmartScreen prend également en compte la réputation des fichiers et d'autres signaux de sécurité. Un logiciel récent ou peu téléchargé peut donc déclencher un avertissement, même si cet avertissement ne prouve pas à lui seul qu'il est malveillant.

Inversement, l'absence d'avertissement ne garantit pas qu'un fichier est sans risque.

## 2. Télécharger ClickBridge depuis la source officielle

Télécharge toujours ClickBridge depuis le dépôt officiel :

**[Releases ClickBridge](https://github.com/TBrassart/ClickBridge/releases/latest)**

Vérifie que le fichier téléchargé est bien l'installateur publié dans la release attendue.

Évite les copies provenant de sites tiers, de liens non vérifiés ou de pièces jointes dont la provenance est incertaine.

## 3. Vérifier l'intégrité du fichier téléchargé

Si la release fournit un manifeste de sommes de contrôle, par exemple `SHA256SUMS.txt`, tu peux vérifier l'empreinte SHA-256 de l'installateur.

Ouvre PowerShell dans le dossier contenant le fichier puis exécute :

```powershell
Get-FileHash .\ClickBridge-Setup.exe -Algorithm SHA256
```

Compare la valeur obtenue avec celle publiée pour `ClickBridge-Setup.exe` dans le manifeste de la même release.

Si les valeurs diffèrent, n'exécute pas le fichier. Télécharge-le de nouveau depuis la source officielle et effectue une nouvelle vérification.

**Important :** une empreinte SHA-256 permet de vérifier que le fichier correspond à l'empreinte de référence. Elle ne prouve pas, à elle seule, l'identité de l'auteur du fichier ni l'absence de code malveillant. La fiabilité de cette vérification dépend également de la provenance du manifeste.

Si aucun manifeste n'est fourni dans la release, ne suppose pas qu'une vérification a été effectuée.

## 4. Que faire si Windows bloque l'installation ?

Si Windows affiche un message du type « Windows a protégé votre ordinateur » :

1. Vérifie que tu as téléchargé l'installateur depuis la release officielle.
2. Vérifie son empreinte si un manifeste est disponible.
3. Si la provenance du fichier est incertaine ou si l'empreinte ne correspond pas, annule l'installation.
4. Si tu as vérifié le fichier et que tu choisis de poursuivre, Windows peut proposer une option **Informations complémentaires**, puis **Exécuter quand même**. Les libellés et options disponibles dépendent de la version de Windows et de ses règles de sécurité.

Cette dernière option n'est pas toujours disponible. Sur un ordinateur administré ou soumis à des politiques de sécurité renforcées, ne cherche pas à contourner les restrictions : demande conseil à l'administrateur.

Ne désactive pas globalement Windows SmartScreen, Microsoft Defender ou les autres protections de sécurité pour installer ClickBridge.

## 5. Que changerait un certificat de signature ?

L'utilisation d'un certificat de signature de code adapté permettrait de signer les fichiers distribués et d'identifier l'éditeur selon les mécanismes de confiance de Windows.

Cela améliorerait la vérifiabilité de l'origine du logiciel, mais ne garantirait pas la disparition immédiate de tous les avertissements SmartScreen. La réputation du fichier et d'autres mécanismes de sécurité peuvent continuer à intervenir.

La signature ne garantit pas non plus que le logiciel est exempt de bugs ou de vulnérabilités.

## 6. Ce que l'absence de signature signifie — et ne signifie pas

L'absence de certificat reconnu signifie que Windows ne peut pas vérifier l'identité de l'éditeur par une signature de code reconnue.

Elle ne signifie pas automatiquement que ClickBridge est malveillant.

De la même manière, un logiciel signé n'est pas automatiquement sûr. Il reste important de vérifier la provenance du téléchargement et de conserver les protections de sécurité actives.

## 7. En cas de doute

Si tu n'es pas certain de l'origine du fichier, si son empreinte ne correspond pas ou si le comportement de l'installateur te paraît suspect, n'exécute pas le fichier.

Télécharge une nouvelle copie depuis les [releases officielles ClickBridge](https://github.com/TBrassart/ClickBridge/releases/latest) et vérifie les informations disponibles avant de poursuivre.

## Voir aussi

- [Installation et première connexion](INSTALLATION.md)
- [Dépannage](TROUBLESHOOTING.md)
- [Dépôt officiel ClickBridge](https://github.com/TBrassart/ClickBridge)
