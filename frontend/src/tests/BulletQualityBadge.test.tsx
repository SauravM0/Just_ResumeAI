import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { BulletQualityBadge } from '../components/ui/BulletQualityBadge'

describe('BulletQualityBadge', () => {
  it('renders a green quality dot for strong bullets and opens details', async () => {
    const user = userEvent.setup()
    render(
      <BulletQualityBadge
        starScore={92}
        hasAction
        hasContext
        hasOutcome
        hasBannedPhrase={false}
      />,
    )

    const badge = screen.getByRole('button', { name: 'Bullet quality: 92/100. Click for details.' })
    expect(badge).toHaveAttribute('title', 'Bullet quality: 92/100. Click for details.')
    expect(badge).toHaveStyle('background: #1D9E75')

    await user.click(badge)

    expect(screen.getByText('Bullet Quality: 92/100')).toBeInTheDocument()
    expect(screen.getByText('Strong action verb')).toBeInTheDocument()
    expect(screen.getByText('Technology/context')).toBeInTheDocument()
    expect(screen.getByText('Outcome/impact')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /improve this bullet/i })).not.toBeInTheDocument()
  })

  it('offers improvement for low-scoring bullets and invokes the callback', async () => {
    const onImprove = vi.fn()
    const user = userEvent.setup()

    render(
      <BulletQualityBadge
        starScore={58}
        hasAction={false}
        hasContext={false}
        hasOutcome
        hasBannedPhrase={false}
        onImprove={onImprove}
      />,
    )

    await user.click(screen.getByRole('button', { name: 'Bullet quality: 58/100. Click for details.' }))
    await user.click(screen.getByRole('button', { name: /improve this bullet/i }))

    expect(onImprove).toHaveBeenCalledTimes(1)
    expect(screen.queryByText('Bullet Quality: 58/100')).not.toBeInTheDocument()
  })

  it('flags banned phrases as red and suppresses improvement action', async () => {
    const user = userEvent.setup()

    render(
      <BulletQualityBadge
        starScore={85}
        hasAction
        hasContext
        hasOutcome
        hasBannedPhrase
        onImprove={vi.fn()}
      />,
    )

    const badge = screen.getByRole('button', { name: 'Bullet quality: 85/100. Click for details.' })
    expect(badge).toHaveStyle('background: #E24B4A')

    await user.click(badge)

    expect(screen.getByText('No banned phrases')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /improve this bullet/i })).not.toBeInTheDocument()
  })
})
