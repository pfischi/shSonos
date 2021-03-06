##Release

v0.3    (2017-02-18)

    -- complete rewrite of widget for Sonos Broker >= 1.0
    -- compatible for SmartVISU 2.8 and 2.9 (untested)

v0.2    (2014-12-05)

    --  fixed issue, that a cover was not shown correctly

v0.1.1  (2014-07-09)

    --  if no album cover is given, a transparent png is shown

v0.1    (2014-07-08)

    --  first release

---
### Requirements

Sonos Broker server min. v1.0b7 (https://github.com/pfischi/shSonos)
Sonos Plugin for smarthome.py (https://github.com/pfischi/shSonos/tree/master/plugin.sonos)
SmarthomeNG >=v1.2 (https://github.com/smarthomeNG)
smartVISU >=v2.8 (http://www.smartvisu.de/)

##### IMPORTANT
It is highly recommended that you use the same Sonos item structure as shown in the 
[Sonos plugin example](https://github.com/pfischi/shSonos/blob/develop/plugin.sonos/examples/sonos.conf). This item
structure always matches the requirements for the Sonos widget. You can edit ```sonos.html``` if you have your own 
structure. 

---
### Integration in smartVISU

Copy **sonos.html**, **sonos.js** and **sonos.css** to your smartVISU widget directory, e.g.

```
/var/www/smartvisu/widgets
```

Copy **sonos_empty.jpg** to the base pic's folder, e.g.
```
/var/www/smartvisu/pages/base/pics/sonos_empty.jpg
```

Edit your page where you want to display the widget and add the following code snippet:

```
{% import "sonos.html" as sonos %}

{% block content %}

<div class="block">
  <div class="set-2" data-role="collapsible-set" data-theme="c" data-content-theme="a" data-mini="true">
    <div data-role="collapsible" data-collapsed="false" >
      {{ sonos.player('sonos_kueche', 'Sonos.Kueche') }}
    </div>
  </div>
</div>

{% endblock %}

```
Rename ```Sonos.Kueche``` to your Sonos item name in SmarthomeNG.
If your're using another root directory than ```/``` for your SmartVISU installtion, you have to adapt the file
`sonos.html` and change the following three entries to your needs:
```
{% set cover_default      = '[YOUR_ROOT_HERE]/pages/base/pics/sonos_empty.jpg' %}

...
<script type="text/javascript" src="[YOUR_ROOT_HERE]/widgets/sonos.js"></script>
<link rel="stylesheet" href="[YOUR_ROOT_HERE]/widgets/sonos.css" type="text/css"/>
...

```