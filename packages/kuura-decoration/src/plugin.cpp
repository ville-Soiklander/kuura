// Plugin entry point of the window decoration (see the "Plugin entry point" block at the
// end of decoration.h).
//
// WHY both registrations: KWin asks the factory for a KDecoration3::Decoration per
// window, and the Window Decorations settings page asks it for a
// KDecoration3::DecorationButton to draw its button previews.
// WHY a separate file: K_PLUGIN_FACTORY_WITH_JSON defines a Q_OBJECT class that moc must
// process together with the configure-time metadata.json; keeping it apart from
// decoration.cpp keeps that moc step independent of the decoration's own code.

#include "button.h"
#include "decoration.h"

#include <KPluginFactory>

K_PLUGIN_FACTORY_WITH_JSON(KuuraDecorationFactory, "metadata.json", registerPlugin<Kuura::Deco::Decoration>();
                           registerPlugin<Kuura::Deco::Button>();)

#include "plugin.moc"
