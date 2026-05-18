interface Props {
  text?: string;
  size?: 'sm' | 'lg';
}

export default function LoadingState({ text = 'Loading...', size = 'lg' }: Props) {
  return (
    <div className="loading-state">
      <div className={`spinner ${size === 'lg' ? 'spinner-lg' : ''}`} />
      <div className="loading-text">{text}</div>
    </div>
  );
}
