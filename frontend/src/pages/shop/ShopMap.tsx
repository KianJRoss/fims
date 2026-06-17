import { Clock, MapPin, Phone } from "lucide-react";

export default function ShopMap() {
  return (
    <div className="mx-auto max-w-7xl px-4 py-10 sm:px-6 lg:px-8">
      <div className="grid gap-6 lg:grid-cols-5">
        <div className="lg:col-span-3 overflow-hidden rounded-3xl border border-slate-100 bg-white shadow-sm">
          <iframe
            title="Bodigons Fireworks location"
            src="https://maps.google.com/maps?q=Bodigon+Fireworks&output=embed"
            className="h-[420px] w-full"
            loading="lazy"
            referrerPolicy="no-referrer-when-downgrade"
          />
        </div>

        <aside className="lg:col-span-2 rounded-3xl border border-slate-100 bg-white p-6 shadow-sm">
          <h1 className="text-2xl font-bold tracking-tight text-slate-900">Find Bodigons Fireworks</h1>
          <p className="mt-2 text-sm text-slate-500">Visit us in person for seasonal inventory and current deals.</p>

          <div className="mt-6 space-y-4">
            <div className="flex items-start gap-3 rounded-2xl border border-slate-100 bg-slate-50 p-4">
              <MapPin className="mt-0.5 h-5 w-5 text-sky-600" />
              <div>
                <div className="font-semibold text-slate-900">123 Main St</div>
                <div className="text-sm text-slate-500">Bodigons Fireworks</div>
              </div>
            </div>

            <div className="flex items-start gap-3 rounded-2xl border border-slate-100 bg-slate-50 p-4">
              <Clock className="mt-0.5 h-5 w-5 text-sky-600" />
              <div>
                <div className="font-semibold text-slate-900">Mon-Sun 9am-10pm</div>
                <div className="text-sm text-slate-500">Open daily throughout the season.</div>
              </div>
            </div>

            <div className="flex items-start gap-3 rounded-2xl border border-slate-100 bg-slate-50 p-4">
              <Phone className="mt-0.5 h-5 w-5 text-sky-600" />
              <div>
                <div className="font-semibold text-slate-900">(555) 000-0000</div>
                <div className="text-sm text-slate-500">Call ahead for product availability.</div>
              </div>
            </div>
          </div>
        </aside>
      </div>
    </div>
  );
}
