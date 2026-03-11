import { ComponentFixture, TestBed } from '@angular/core/testing';

import { GeolocationPopupComponent } from './geolocation-popup.component';

describe('GeolocationPopupComponent', () => {
  let component: GeolocationPopupComponent;
  let fixture: ComponentFixture<GeolocationPopupComponent>;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [GeolocationPopupComponent]
    })
    .compileComponents();

    fixture = TestBed.createComponent(GeolocationPopupComponent);
    component = fixture.componentInstance;
    fixture.detectChanges();
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });
});
