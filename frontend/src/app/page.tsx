import Link from "next/link";
import { ArrowRight, BookOpen, Brain, Code2, GraduationCap, Mail, UserCheck } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

const LINKS = [
  { href: process.env.NEXT_PUBLIC_GITHUB_URL, label: "GitHub", icon: Code2 },
  { href: process.env.NEXT_PUBLIC_NOTEBOOK_URL, label: "Training notebook", icon: BookOpen },
  { href: process.env.NEXT_PUBLIC_MODEL_CARD_URL, label: "Model card", icon: GraduationCap },
].filter((l) => !!l.href);

const ROLES = [
  {
    icon: Brain,
    title: "Junior clerk",
    who: "A small fine-tuned model (Gemma 3, 270M)",
    text: "Reads most emails in seconds on a cheap CPU and pulls out what the customer wants: parts, quantities, deadlines, what's missing.",
  },
  {
    icon: GraduationCap,
    title: "Senior expert",
    who: "A large model (Gemini 3.8 Flash)",
    text: "Called only when the clerk is unsure. It costs more per email, so the router keeps it for the hard cases.",
  },
  {
    icon: UserCheck,
    title: "Manager",
    who: "A human",
    text: "Approves every quote before it goes out. Their corrections become training data, and a new clerk is only promoted if it passes a sealed exam.",
  },
];

export default function Home() {
  return (
    <div className="mx-auto max-w-6xl px-4 py-14 md:py-20">
      <section className="max-w-3xl">
        <p className="mb-3 inline-flex items-center gap-2 rounded-full border px-3 py-1 text-xs text-muted-foreground">
          <Mail className="size-3" /> Fine-tuned small model + agent harness
        </p>
        <h1 className="text-4xl font-semibold tracking-tight md:text-5xl">Messy customer emails to draft quotes in seconds.</h1>
        <p className="mt-4 text-lg text-muted-foreground">
          An industrial parts distributor gets quote requests full of typos, shorthand, &ldquo;same as last time&rdquo; and
          &ldquo;whatever fits my unit&rdquo;. QuoteDesk reads them, finds the parts, checks stock, applies the customer&apos;s
          pricing and drafts the quote for a human to approve.
        </p>
        <div className="mt-8 flex flex-wrap gap-3">
          <Button asChild size="lg">
            <Link href="/playground?sample=clean-multi">
              Try a sample email <ArrowRight className="size-4" />
            </Link>
          </Button>
          <Button asChild size="lg" variant="outline">
            <Link href="/how-it-works">How it works</Link>
          </Button>
        </div>
        {LINKS.length > 0 && (
          <div className="mt-6 flex flex-wrap gap-4 text-sm">
            {LINKS.map((l) => (
              <a key={l.label} href={l.href} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1.5 text-muted-foreground hover:text-foreground">
                <l.icon className="size-4" /> {l.label}
              </a>
            ))}
          </div>
        )}
      </section>

      <section className="mt-16 grid gap-4 md:grid-cols-3">
        {ROLES.map((r, i) => (
          <Card key={r.title}>
            <CardHeader>
              <div className="mb-2 flex items-center gap-2">
                <span className="grid size-8 place-items-center rounded-md bg-primary/10 text-primary">
                  <r.icon className="size-4" />
                </span>
                <span className="text-xs text-muted-foreground">Step {i + 1}</span>
              </div>
              <CardTitle>{r.title}</CardTitle>
              <CardDescription>{r.who}</CardDescription>
            </CardHeader>
            <CardContent className="text-sm text-muted-foreground">{r.text}</CardContent>
          </Card>
        ))}
      </section>

      <section className="mt-16 grid gap-6 md:grid-cols-3">
        {[
          ["Results", "/results", "Base vs fine-tuned vs large model: accuracy, speed and cost, measured on a sealed exam."],
          ["Models", "/models", "Version history: retrains that were promoted, and ones the safety gate rejected."],
          ["Traces", "/traces", "Every quote keeps a full trace of each step, model call, tool call and cost."],
        ].map(([t, href, d]) => (
          <Link key={href} href={href} className="group rounded-lg border p-5 transition-colors hover:bg-muted/50">
            <p className="flex items-center gap-1 font-medium">
              {t} <ArrowRight className="size-4 transition-transform group-hover:translate-x-0.5" />
            </p>
            <p className="mt-1 text-sm text-muted-foreground">{d}</p>
          </Link>
        ))}
      </section>
    </div>
  );
}
