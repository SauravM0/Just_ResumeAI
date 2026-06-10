export interface FlowStep {
  id: string;
  label: string;
  shortLabel?: string;
  icon?: string;
}

interface Props {
  steps: FlowStep[];
  currentStep: number;
  completedSteps?: number[];
  className?: string;
}

/**
 * Guided flow stepper — shows progress across resume creation steps.
 * On desktop: horizontal with labels.
 * On mobile: compact dots with current step label.
 */
export default function FlowStepper({ steps, currentStep, completedSteps = [], className = '' }: Props) {
  return (
    <div className={`flow-stepper ${className}`} role="navigation" aria-label="Resume creation progress">
      {/* Desktop: full horizontal stepper */}
      <div className="flow-stepper-desktop" aria-hidden="true">
        {steps.map((step, index) => {
          const isCompleted = completedSteps.includes(index) || index < currentStep;
          const isCurrent = index === currentStep;
          const isUpcoming = index > currentStep;

          return (
            <div key={step.id} className="flow-stepper-step">
              <div className={`flow-stepper-node ${isCompleted ? 'complete' : ''} ${isCurrent ? 'current' : ''} ${isUpcoming ? 'upcoming' : ''}`}>
                {isCompleted ? (
                  <span className="flow-stepper-check">✓</span>
                ) : (
                  <span className="flow-stepper-num">{index + 1}</span>
                )}
              </div>
              <div className="flow-stepper-label">
                <span className="flow-stepper-label-text">{step.label}</span>
              </div>
              {index < steps.length - 1 && (
                <div className={`flow-stepper-line ${isCompleted ? 'complete' : ''}`} />
              )}
            </div>
          );
        })}
      </div>

      {/* Mobile: compact bar */}
      <div className="flow-stepper-mobile" aria-hidden="true">
        <div className="flow-stepper-mobile-bar">
          {steps.map((_, index) => {
            const isCompleted = completedSteps.includes(index) || index < currentStep;
            const isCurrent = index === currentStep;
            return (
              <div
                key={index}
                className={`flow-stepper-mobile-segment ${isCompleted ? 'complete' : ''} ${isCurrent ? 'current' : ''}`}
              />
            );
          })}
        </div>
        <div className="flow-stepper-mobile-label">
          Step {currentStep + 1} of {steps.length}: {steps[currentStep]?.label}
        </div>
      </div>

      {/* Screen reader */}
      <span className="sr-only">
        Step {currentStep + 1} of {steps.length}: {steps[currentStep]?.label}
      </span>
    </div>
  );
}
