import { Clock, MapPin, Phone } from "lucide-react";

export default function ShopMap() {
  return (
    <div className="mx-auto max-w-7xl px-4 py-10 text-slate-100 sm:px-6 lg:px-8">
      <div className="grid gap-6 lg:grid-cols-5">
        <div className="lg:col-span-3 overflow-hidden rounded-3xl border border-white/10 bg-slate-900/80 shadow-xl shadow-slate-950/20">
          <iframe
            title="Bodigon Fireworks location"
            src="https://maps.google.com/maps?q=Bodigon+Fireworks&output=embed"
            className="h-[420px] w-full"
            loading="lazy"
            referrerPolicy="no-referrer-when-downgrade"
          />
        </div>

        <aside className="lg:col-span-2 rounded-3xl border border-white/10 bg-slate-900/80 p-6 shadow-xl shadow-slate-950/20">
          <h1 className="text-2xl font-bold tracking-tight text-white">Find Bodigon Fireworks</h1>
          <p className="mt-2 text-sm text-slate-300">Visit us in person for seasonal inventory and current deals.</p>

          <div className="mt-6 space-y-4">
            <div className="flex items-start gap-3 rounded-2xl border border-white/10 bg-white/5 p-4">
              <MapPin className="mt-0.5 h-5 w-5 text-sky-300" />
              <div>
                <div className="font-semibold text-white">2740 US-6, Kendallville, IN 46755, USA</div>
                <div className="text-sm text-slate-300">Bodigon Fireworks</div>
              </div>
            </div>

            <div className="flex items-start gap-3 rounded-2xl border border-white/10 bg-white/5 p-4">
              <Clock className="mt-0.5 h-5 w-5 text-sky-300" />
              <div>
                <div className="font-semibold text-white">9 AM to 7 PM, likely later</div>
                <div className="text-sm text-slate-300">Expect 10 PM hours for the 2nd through the 5th.</div>
              </div>
            </div>

            <div className="flex items-start gap-3 rounded-2xl border border-white/10 bg-white/5 p-4">
              <Phone className="mt-0.5 h-5 w-5 text-sky-300" />
              <div>
                <div className="font-semibold text-white">(260) 347-8595</div>
                <div className="text-sm text-slate-300">Call ahead for product availability.</div>
              </div>
            </div>
          </div>
        </aside>
      </div>
    </div>
  );
}
