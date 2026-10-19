import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting } from '@angular/common/http/testing';
import { provideRouter } from '@angular/router';

import { GeolocationPopupComponent } from './geolocation-popup.component';

describe('GeolocationPopupComponent', () => {
  let component: GeolocationPopupComponent;
  let fixture: ComponentFixture<GeolocationPopupComponent>;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [GeolocationPopupComponent],
      providers: [provideHttpClient(), provideHttpClientTesting(), provideRouter([])],
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
