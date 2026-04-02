import { ChangeDetectionStrategy, Component, Input } from '@angular/core';
import { NgStyle } from '@angular/common';

@Component({
  selector: 'app-blip-marker',
  standalone: true,
  imports: [NgStyle],
  templateUrl: './blip-marker.component.html',
  styleUrl: './blip-marker.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class BlipMarkerComponent {
  @Input() color: string = '92, 157, 255';
  @Input() coreSize: number = 8;
  @Input() ringSize: number = 25;
  @Input() ringWidth: number = 2;
  @Input() duration: number = 3;
  @Input() haloSize: number = 25;
  @Input() pulseOpacity: number = 1;

  get hostStyle(): Record<string, string> {
    return {
      '--blip-r-g-b':        this.color,
      '--blip-core-size':    this.coreSize + 'px',
      '--blip-ring-size':    this.ringSize + 'px',
      '--blip-ring-width':   this.ringWidth + 'px',
      '--blip-duration':     this.duration + 's',
      '--blip-halo-size':    this.haloSize + 'px',
      '--blip-pulse-opacity': String(this.pulseOpacity),
    };
  }
}
