import { Link } from 'react-router-dom'
import type { ReactNode } from 'react'

const CONTACT_EMAIL = 'jadenmengl@gmail.com'

const LAST_UPDATED = 'August 23, 2026'

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="mt-9">
      <h2 className="m-0 font-display text-[21px] font-normal text-ink">{title}</h2>
      <div className="mt-3 flex flex-col gap-3 text-[15px] leading-relaxed text-muted">{children}</div>
    </section>
  )
}

export function Privacy() {
  return (
    <div className="flex min-h-screen flex-col bg-bg px-9 py-7">
      <Link to="/" className="self-start text-[13.5px] text-muted no-underline hover:text-pine">
        ← Back to home
      </Link>

      <main className="rise mx-auto w-full max-w-2xl flex-1 pb-20 pt-8">
        <h1 className="m-0 font-display text-[34px] font-normal leading-tight text-ink">
          Privacy Policy
        </h1>
        <p className="mt-2 font-mono text-[12.5px] text-faint">Last updated {LAST_UPDATED}</p>

        <p className="mt-7 text-[15px] leading-relaxed text-ink-soft">
          Nota is a voice-driven music notation editor. This policy describes what the service
          collects, where it goes, and how to get rid of it. It is written to describe how Nota
          actually works rather than to cover every hypothetical.
        </p>

        <Section title="What Nota stores">
          <p>
            <strong className="font-medium text-ink">Your account.</strong> Your name and email
            address. If you sign up with a password, only a bcrypt hash of it is stored — never the
            password itself. If you sign in with Google, no password is stored at all.
          </p>
          <p>
            <strong className="font-medium text-ink">Your scores.</strong> The notation files you
            upload, the edited versions Nota saves as you work, the undo history for each score, a
            small rendered preview image, and a log of the commands you have issued against each
            score.
          </p>
          <p>
            <strong className="font-medium text-ink">Nothing else.</strong> Nota has no analytics,
            no advertising, and no third-party trackers. It sets one cookie, which keeps you signed
            in. Your data is never sold or shared for marketing.
          </p>
        </Section>

        <Section title="Where your voice goes">
          <p>
            This is the part worth reading closely, because Nota listens to a microphone.
          </p>
          <p>
            <strong className="font-medium text-ink">Wake-word detection runs entirely in your
            browser.</strong> When you arm “Hey Nota,” the listening and matching happen locally on
            your own device. Audio is not streamed anywhere while Nota waits for the wake phrase,
            and nothing is recorded or sent until you actively speak a command.
          </p>
          <p>
            <strong className="font-medium text-ink">Spoken commands are transcribed by OpenAI.</strong>{' '}
            Once you issue a command, that short audio recording is sent to OpenAI’s Whisper API to
            be turned into text. Nota does not keep the audio after transcription.
          </p>
          <p>
            <strong className="font-medium text-ink">Commands are interpreted by Anthropic.</strong>{' '}
            The transcribed text, your recent commands for that score, and a short description of
            the score (its title, parts, measure count, and time signatures) are sent to Anthropic’s
            Claude API to work out which notation edit you asked for. The score file itself is never
            sent — edits are applied on Nota’s own server.
          </p>
          <p>
            Both providers process this data under their own terms. Spoken replies are produced by
            your browser’s built-in speech synthesis, so nothing leaves your device for that.
          </p>
        </Section>

        <Section title="Other services Nota uses">
          <p>
            <strong className="font-medium text-ink">Google sign-in</strong>, only if you choose it.
            Nota receives your email address, name, and the fact that Google has verified the
            address. Nota never receives your Google password and asks for no access to any other
            Google service.
          </p>
          <p>
            <strong className="font-medium text-ink">Email</strong>, used solely to send password
            reset links when you request one.
          </p>
          <p>
            <strong className="font-medium text-ink">PDF import</strong> runs optical music
            recognition on Nota’s own server. Uploaded PDFs are not sent to any outside service, and
            the original file is discarded once conversion finishes.
          </p>
        </Section>

        <Section title="Deleting your data">
          <p>
            Deleting a score removes it completely: the file, every undo snapshot, its preview
            image, and the full command history for it.
          </p>
          <p>
            To delete your entire account, email{' '}
            <a className="text-pine no-underline hover:text-brass" href={`mailto:${CONTACT_EMAIL}`}>
              {CONTACT_EMAIL}
            </a>{' '}
            from the address you signed up with, and the account and everything in it will be
            removed.
          </p>
        </Section>

        <Section title="Security and honesty about limits">
          <p>
            Traffic is encrypted in transit, passwords are hashed with bcrypt, password reset links
            are single-use and expire after an hour, and score files are readable only by the
            account that uploaded them.
          </p>
          <p>
            Nota is a small independent project rather than a company with a security team. It is
            built carefully, but please do not store anything here that would be genuinely damaging
            to lose or expose, and keep your own copies of work that matters to you.
          </p>
        </Section>

        <Section title="Children">
          <p>
            Nota is not directed at children under 13 and does not knowingly collect their
            information.
          </p>
        </Section>

        <Section title="Changes and contact">
          <p>
            If this policy changes in a way that affects how your data is handled, the date at the
            top of this page will change. Questions about any of this can go to{' '}
            <a className="text-pine no-underline hover:text-brass" href={`mailto:${CONTACT_EMAIL}`}>
              {CONTACT_EMAIL}
            </a>
            .
          </p>
        </Section>
      </main>
    </div>
  )
}
